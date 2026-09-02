# backend/app/tasks/script_tasks.py
"""Script conversion Celery tasks."""
import logging
import uuid
from typing import List

from app.tasks import celery_app
from app.core.database import AsyncSessionLocal
from app.core.sse import SSEStream
from app.services.script_convert_service import ScriptConvertService
from app.services.element_service import ElementLocatorLookup, ElementService
from app.services.ai_gateway import AIGateway

logger = logging.getLogger(__name__)


async def convert_scripts_task_impl(session_id: str, cases: List[dict],
                                    gateway, lookup, db, ai_optimize: bool = False) -> dict:
    """批量转换实现 (供直接调用测试)。"""
    sse = _SSEWrapper(SSEStream(session_id))
    svc = ScriptConvertService(db=db, gateway=gateway)
    generated = 0
    tokens = 0
    for i, case in enumerate(cases):
        progress = i / max(len(cases), 1)
        try:
            asset = await svc.convert_one(case, sse, lookup=lookup, ai_optimize=ai_optimize)
            await svc.persist(asset)
            generated += 1
        except Exception as e:
            logger.warning(f"case {case.get('id')} convert failed: {type(e).__name__}: {e}")
            await sse.send_message(type="error", stage="convert_script",
                                   content=f"用例 {case.get('id')} 失败: {e}", progress=progress)
        tokens = getattr(gateway, "tokens", tokens)
    await db.commit()
    return {"status": "done", "generated_count": generated, "tokens_used": tokens}


class _SSEWrapper:
    """SSEStream 适配 (提供 send_message kwargs 接口)。"""
    def __init__(self, stream: SSEStream):
        self._stream = stream

    async def send_message(self, **kw):
        await self._stream.send_message(
            type=kw.get("type", "system"),
            stage=kw.get("stage", "convert_script"),
            content=kw.get("content", ""),
            progress=kw.get("progress", 0.0),
            tokens_used=kw.get("tokens_used", 0),
        )


@celery_app.task(bind=True, name="convert_scripts_task")
def convert_scripts_task(self, session_id: str, case_ids: list, project_id: str, ai_optimize: bool = False):
    """Celery 入口: 查用例 -> 转换 -> 写 ScriptAsset + 自动化状态联动。"""
    import asyncio
    from sqlalchemy import select
    from app.models.test_case import TestCase, ScriptAsset, TestPoint
    from app.models.case_batch import CaseBatch

    async def _run():
        async with AsyncSessionLocal() as db:
            # #case-batch T4: 联查批次名 (脚本命名 + 脚本库来源列)
            result = await db.execute(
                select(TestCase, CaseBatch.batch_name)
                .outerjoin(CaseBatch, TestCase.batch_id == CaseBatch.id)
                .where(
                    TestCase.id.in_([uuid.UUID(c) for c in case_ids]),
                    TestCase.is_finalized.is_(True),
                )
            )
            cases = []
            for tc, batch_name in result.all():
                d = tc.to_dict()
                d["batch_name"] = batch_name
                cases.append(d)
            # #8 偏差 J: module 从 TestCase.point_id → TestPoint.page_name 推导
            point_ids = {c.get("point_id") for c in cases if c.get("point_id")}
            page_by_point = {}
            if point_ids:
                pres = await db.execute(
                    select(TestPoint).where(TestPoint.id.in_([uuid.UUID(p) for p in point_ids])))
                page_by_point = {str(p.id): p.page_name for p in pres.scalars().all()}
            for c in cases:
                c["module"] = page_by_point.get(c.get("point_id"))
            gateway = _CountingGateway(AIGateway())
            element_svc = ElementService(db)
            lookup = ElementLocatorLookup(element_svc)
            summary = await convert_scripts_task_impl(session_id, cases, gateway, lookup, db, ai_optimize=ai_optimize)
            # 联动 automation_status -> converted (CASE-MGMT-04)
            await db.execute(
                TestCase.__table__.update().where(
                    TestCase.id.in_([uuid.UUID(c) for c in case_ids])
                ).values(automation_status="converted")
            )
            await db.commit()
            return summary

    return asyncio.run(_run())


class _CountingGateway:
    """包装 AIGateway 累计 tokens (修 #2 Token 实时推送恒 0)。"""
    def __init__(self, gateway):
        self._gw = gateway
        self.tokens = 0

    async def chat(self, messages, **kw):
        resp = await self._gw.chat(messages, **kw)
        self.tokens += resp.get("tokens", 0)
        return resp


@celery_app.task(bind=True, name="run_scripts_task")
def run_scripts_task(self, session_id: str, script_id: str = None, script_ids: list = None,
                     config: dict = None, exec_type: str = None, script_content: str = None,
                     target_url: str = None, headless: bool = True):
    """执行脚本任务: 建 execution_record → ScriptExecutor.execute → 写 detail → 更新 record → commit.

    T6 遗留: ScriptExecutor.execute 未调 db.add(detail)/db.commit(), 这里补持久化。
    """
    import asyncio
    from sqlalchemy import select as _sel
    from app.models.execution import ExecutionRecord
    from app.models.test_case import ScriptAsset
    from app.services.script_executor import ScriptExecutor
    from app.core.storage import storage_client

    async def _run():
        async with AsyncSessionLocal() as db:
            # config dict → 对象 (ScriptExecutor 用 getattr 取 headless/timeout/max_failures)
            cfg = config or {}
            config_obj = type("C", (), {
                "headless": cfg.get("headless", headless),
                "timeout": cfg.get("timeout", 60),
                "max_failures": cfg.get("max_failures", 8),
            })()
            gateway = _CountingGateway(AIGateway())
            element_svc = ElementService(db)
            executor = ScriptExecutor(
                db=db, gateway=gateway, storage=storage_client,
                element_svc=element_svc,
            )
            sse = _SSEWrapper(SSEStream(session_id))

            # quick-run: 不落库, 不建 ExecutionRecord (project_id 列 nullable=False,
            # quick-run 无归属项目 → 跳过 record + detail, 仅 SSE 直播)
            if script_content:
                sa = ScriptAsset(
                    case_id=None, project_id=None, name="quick-run",
                    content=script_content, version=1, status="confirmed",
                    category="uncategorized", step_mapping=[], locator_source="none_draft",
                )
                detail = await executor.execute(
                    sa, config_obj, target_url, sse, execution_record=None, page=None,
                )
                # detail is None (quick-run skips ExecutionDetail), 无需 db.add
                await db.commit()
                return {"session_id": session_id, "status": "done"}

            # single / batch: 先查 ScriptAsset 拿 project_id 再建 ExecutionRecord
            if script_ids:
                targets = []
                for sid in script_ids:
                    r = await db.execute(
                        _sel(ScriptAsset).where(ScriptAsset.id == uuid.UUID(sid))
                    )
                    sa = r.scalar_one_or_none()
                    if sa:
                        targets.append(sa)
            else:
                r = await db.execute(
                    _sel(ScriptAsset).where(ScriptAsset.id == uuid.UUID(script_id))
                )
                sa = r.scalar_one_or_none()
                targets = [sa] if sa else []

            project_id = targets[0].project_id if targets else None
            er = ExecutionRecord(
                exec_id=f"exec-{session_id[:8]}", project_id=project_id,
                exec_type=exec_type or ("batch" if script_ids else "single"),
                status="running", total_cases=len(targets),
            )
            db.add(er)
            await db.flush()

            cfg_obj = config or {}
            fail_fast = bool(cfg_obj.get("fail_fast", False))
            details = []
            for sa in targets:
                detail = await executor.execute(
                    sa, config_obj, target_url, sse, er, page=None,
                )
                if detail is not None:
                    # ExecutionDetail.case_id 写入 (关联到脚本所属用例)
                    detail.case_id = getattr(sa, "case_id", None)
                    details.append(detail)
                    if fail_fast and detail.status == "fail":
                        break  # 失败策略=停止: 脚本级 fail-fast (spec 偏差 K)
            # 持久化 detail (T6 遗留: execute 未 db.add, 这里补)
            for d in details:
                db.add(d)
            # 更新 execution_record 汇总
            passed = sum(1 for d in details if d.status == "pass")
            failed = sum(1 for d in details if d.status == "fail")
            total = len(details)
            er.passed_count = passed
            er.fail_count = failed
            er.total_cases = total
            er.pass_rate = round((passed / total * 100), 2) if total else 0
            er.tokens_used = getattr(gateway, "tokens", 0)
            er.status = "done"
            await db.commit()
            return {"session_id": session_id, "status": "done",
                    "passed": passed, "failed": failed, "total": total}

    return asyncio.run(_run())
