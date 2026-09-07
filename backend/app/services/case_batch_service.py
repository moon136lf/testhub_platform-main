"""生成批次服务: 建批次 / 批内用例计数回填."""
import logging
from datetime import datetime

from sqlalchemy import select, func

from app.models.case_batch import CaseBatch
from app.models.test_case import TestCase
from app.services.batch_naming import build_batch_name

logger = logging.getLogger(__name__)


class CaseBatchService:
    def __init__(self, db):
        self.db = db

    async def create_batch(self, project_id, batch_type, ts=None,
                           source_id=None, requirement=None) -> CaseBatch:
        """建批次记录。batch_name 按命名规范生成；同项目重名(同秒重试)时
        追加 '-2' 后缀兜底。"""
        ts = ts or datetime.now()
        name = build_batch_name(batch_type, ts, requirement)
        if await self._name_exists(project_id, name):
            name = f"{name}-2"[:200]
        batch = CaseBatch(
            project_id=project_id, batch_name=name, batch_type=batch_type,
            source_id=source_id, case_count=0,
        )
        self.db.add(batch)
        await self.db.flush()
        return batch

    async def _name_exists(self, project_id, name) -> bool:
        r = await self.db.execute(
            select(CaseBatch.id).where(CaseBatch.project_id == project_id,
                                       CaseBatch.batch_name == name).limit(1))
        return r.scalar_one_or_none() is not None

    async def update_case_count(self, batch_id, delta: int):
        """生成完成后回填批次用例数。

        以批内实际未删用例数为准（实时 COUNT），而非累加 delta——
        任务中断/重跑时累加会漂移，实时统计永远与列表一致。
        """
        batch = await self.db.get(CaseBatch, batch_id)
        if batch:
            r = await self.db.execute(
                select(func.count(TestCase.id)).where(
                    TestCase.batch_id == batch_id,
                    TestCase.is_deleted.is_(False)))
            batch.case_count = r.scalar() or 0
            await self.db.flush()
