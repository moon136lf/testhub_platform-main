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
    from app.models.test_case import TestCase, ScriptAsset

    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TestCase).where(
                    TestCase.id.in_([uuid.UUID(c) for c in case_ids]),
                    TestCase.is_finalized.is_(True),
                )
            )
            cases = [c.to_dict() for c in result.scalars().all()]
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
