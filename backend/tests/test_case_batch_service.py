"""CaseBatchService 测试（mock db，真实逻辑）"""
import asyncio
from unittest.mock import MagicMock
from datetime import datetime

from app.services.case_batch_service import CaseBatchService


def _db():
    db = MagicMock()
    db.added = []

    async def _flush():
        pass

    db.flush = _flush
    db.add = lambda o: db.added.append(o)

    async def _execute(q):  # 查重默认不存在
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r
    db.execute = _execute
    return db


class TestCreateBatch:
    def test_create_whitescan_api_batch(self):
        db = _db()
        svc = CaseBatchService(db)
        batch = asyncio.run(svc.create_batch(
            project_id="p1", batch_type="whitescan_api",
            ts=datetime(2026, 9, 2, 14, 30, 25), source_id="scan-1"))
        assert db.added == [batch]
        assert batch.batch_name == "白盒测试生成接口回归用例20260902143025"
        assert batch.batch_type == "whitescan_api"
        assert batch.source_id == "scan-1"

    def test_duplicate_name_appends_suffix(self):
        db = _db()

        async def _execute(q):  # 查重命中（重名存在）
            r = MagicMock()
            r.scalar_one_or_none.return_value = 42
            return r
        db.execute = _execute
        svc = CaseBatchService(db)
        batch = asyncio.run(svc.create_batch(
            project_id="p1", batch_type="whitescan_api",
            ts=datetime(2026, 9, 2, 14, 30, 25)))
        assert batch.batch_name.endswith("-2")
        assert batch.batch_name == "白盒测试生成接口回归用例20260902143025-2"

    def test_create_ai_batch_with_requirement(self):
        db = _db()
        svc = CaseBatchService(db)
        batch = asyncio.run(svc.create_batch(
            project_id="p1", batch_type="ai_generate",
            ts=datetime(2026, 9, 2, 14, 30, 25), requirement="用户登录功能需求说明"))
        assert batch.batch_name == "用户登录功能需求说明生成的用例20260902143025"


class TestUpdateCaseCount:
    def test_increment(self):
        db = _db()
        batch = MagicMock()
        batch.case_count = 5

        async def _get(cls, bid):
            return batch
        db.get = _get
        svc = CaseBatchService(db)
        asyncio.run(svc.update_case_count("b1", 3))
        assert batch.case_count == 8
