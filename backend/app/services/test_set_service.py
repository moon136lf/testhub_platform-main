"""测试集服务（阶段2）：CRUD + 用例增删 + 执行编排（执行在 Task 4 追加）。"""
import logging
import uuid as _uuid
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_set import TestSet

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
