"""测试集服务（阶段2）：CRUD + 用例增删 + 执行编排（执行在 Task 4 追加）。"""
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_set import TestSet
from app.tasks.script_tasks import run_scripts_task

logger = logging.getLogger(__name__)

# 可编辑字段白名单
_EDITABLE_FIELDS = {"name", "description"}


def _to_uuid(value: str) -> Optional[UUID]:
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


class TestSetService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_set(self, project_id: str, name: str, case_ids: List[str],
                         source: str = "manual", description: str = "") -> TestSet:
        """创建测试集。名称空白/用例为空/同项目重名抛 ValueError。"""
        if not name or not name.strip():
            raise ValueError("测试集名称不能为空")
        if not case_ids:
            raise ValueError("测试集至少需要一条用例")
        dup = await self.db.execute(
            select(TestSet).where(TestSet.project_id == project_id,
                                  TestSet.name == name.strip()).limit(1))
        if dup.scalar_one_or_none():
            raise ValueError(f"测试集「{name.strip()}」已存在")
        ts = TestSet(project_id=project_id, name=name.strip()[:100],
                     case_ids=list(case_ids), source=source or "manual",
                     description=(description or "")[:500] or None)
        self.db.add(ts)
        await self.db.commit()
        return ts

    async def update_set(self, set_id: str, fields: Dict) -> TestSet:
        """编辑（白名单字段）。"""
        ts = await self.db.get(TestSet, _uuid.UUID(set_id))
        if not ts:
            raise ValueError("测试集不存在")
        for k, v in fields.items():
            if k not in _EDITABLE_FIELDS:
                raise ValueError(f"字段不可编辑: {k}")
            setattr(ts, k, (v or "").strip()[:100] if k == "name" and v else v)
        await self.db.commit()
        return ts

    async def delete_set(self, set_id: str) -> None:
        ts = await self.db.get(TestSet, _uuid.UUID(set_id))
        if not ts:
            raise ValueError("测试集不存在")
        await self.db.delete(ts)
        await self.db.commit()

    async def list_sets(self, project_id: str) -> List[TestSet]:
        if not project_id:
            return []
        result = await self.db.execute(
            select(TestSet).where(TestSet.project_id == project_id)
            .order_by(TestSet.updated_at.desc()))
        return result.scalars().all()

    async def add_cases(self, set_id: str, case_ids: List[str]) -> None:
        """合并用例（去重）。"""
        ts = await self.db.get(TestSet, _uuid.UUID(set_id))
        if not ts:
            raise ValueError("测试集不存在")
        existing = set(ts.case_ids or [])
        merged = list(ts.case_ids or [])
        for c in case_ids:
            if c not in existing:
                merged.append(c)
                existing.add(c)
        ts.case_ids = merged
        await self.db.commit()

    async def remove_case(self, set_id: str, case_id: str) -> None:
        ts = await self.db.get(TestSet, _uuid.UUID(set_id))
        if not ts:
            raise ValueError("测试集不存在")
        if case_id in (ts.case_ids or []):
            ts.case_ids = [c for c in ts.case_ids if c != case_id]
            await self.db.commit()

    async def run_set(self, set_id: str, headless: bool = True,
                      fail_fast: bool = False, timeout: int = 60) -> Dict:
        """执行测试集：case_ids → 每条最新 ScriptAsset → run_scripts_task（exec_type=ui_testset）。"""
        from app.models.test_case import ScriptAsset

        ts = await self.db.get(TestSet, _uuid.UUID(set_id))
        if not ts:
            raise ValueError("测试集不存在")
        if not ts.case_ids:
            raise ValueError("测试集为空，请先添加用例")

        case_uuids = [_uuid.UUID(c) for c in ts.case_ids if _to_uuid(c)]
        if not case_uuids:
            raise ValueError("用例ID均无效")
        result = await self.db.execute(
            select(ScriptAsset).where(ScriptAsset.case_id.in_(case_uuids))
            .order_by(ScriptAsset.created_at.desc()))
        all_scripts = result.scalars().all()
        # 每 case 取最新一条（按 created_at 降序，首个即最新）
        by_case = {}
        for s in all_scripts:
            cid = str(getattr(s, "case_id", "") or "")
            by_case.setdefault(cid, s)
        script_ids = [str(s.id) for s in by_case.values()]
        if not script_ids:
            raise ValueError("测试集中的用例尚无已转换脚本，请先在「用例转自动化脚本」页转换")

        session_id = str(_uuid.uuid4())
        config = {"headless": headless, "timeout": timeout,
                  "max_failures": 1 if fail_fast else 100, "fail_fast": fail_fast}
        task = run_scripts_task.delay(session_id=session_id, script_ids=script_ids,
                                      config=config, exec_type="ui_testset")
        ts.status = "running"
        # 与 run_scripts_task 的 exec_id 生成规则一致，供报告聚合后查
        ts.last_exec_id = f"exec-{session_id[:8]}"
        await self.db.commit()
        return {"session_id": session_id, "task_id": task.id,
                "sse_url": f"/api/sse/stream/{session_id}", "script_count": len(script_ids)}

    async def get_report(self, set_id: str) -> Optional[Dict]:
        """测试集报告：按 last_exec_id 查 ExecutionRecord + ExecutionDetail（含失败截图）。"""
        from app.models.execution import ExecutionRecord, ExecutionDetail

        ts = await self.db.get(TestSet, _uuid.UUID(set_id))
        if not ts:
            raise ValueError("测试集不存在")
        if not ts.last_exec_id:
            return None
        er_result = await self.db.execute(
            select(ExecutionRecord).where(ExecutionRecord.exec_id == ts.last_exec_id))
        er = er_result.scalar_one_or_none()
        if not er:
            return None
        details_result = await self.db.execute(
            select(ExecutionDetail).where(ExecutionDetail.execution_record_id == er.id)
            .order_by(ExecutionDetail.created_at))
        details = details_result.scalars().all()
        return {
            "record": {
                "exec_id": er.exec_id, "status": er.status,
                "total_cases": er.total_cases, "passed": er.passed_count,
                "failed": er.fail_count, "pass_rate": float(er.pass_rate or 0),
                "duration_ms": er.duration_ms,
            },
            "pass_rate": float(ts.last_pass_rate or 0),
            "details": [{
                "status": d.status, "error_type": d.error_type,
                "screenshot_url": d.screenshot_url, "duration_ms": d.duration_ms,
                "error_message": getattr(d, "error_msg", None),
            } for d in details],
        }

    async def sync_result_from_execution(self, set_id: str) -> None:
        """从 ExecutionRecord 回写测试集执行结果（报告聚合时顺带同步，幂等）。"""
        from app.models.execution import ExecutionRecord

        ts = await self.db.get(TestSet, _uuid.UUID(set_id))
        if not ts or not ts.last_exec_id:
            return
        er_result = await self.db.execute(
            select(ExecutionRecord).where(ExecutionRecord.exec_id == ts.last_exec_id))
        er = er_result.scalar_one_or_none()
        if not er or er.status != "done":
            return
        ts.last_run_at = datetime.now(timezone.utc)
        ts.last_pass_rate = float(er.pass_rate or 0)
        ts.status = "done"
        await self.db.commit()
