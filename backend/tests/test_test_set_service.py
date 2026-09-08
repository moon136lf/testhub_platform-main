"""TestSetService 测试（mock db）"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4

from app.services.test_set_service import TestSetService


def _db():
    db = MagicMock()
    db.commit = AsyncMock()

    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = []
        r.scalar_one_or_none.return_value = None
        return r
    db.execute = _execute
    return db


def _exec(rows):
    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        return r
    return _execute


class TestCrud:
    @pytest.mark.asyncio
    async def test_create_with_case_ids(self):
        db = _db()
        added = []
        db.add = lambda o: added.append(o)
        db.flush = AsyncMock()

        svc = TestSetService(db)
        ts = await svc.create_set("p1", "冒烟集", ["c1", "c2"], source="convert_page")
        assert added[0].name == "冒烟集"
        assert added[0].case_ids == ["c1", "c2"]
        assert added[0].source == "convert_page"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_empty_name_raises(self):
        svc = TestSetService(_db())
        with pytest.raises(ValueError, match="名称"):
            await svc.create_set("p1", "  ", ["c1"])

    @pytest.mark.asyncio
    async def test_create_empty_cases_raises(self):
        svc = TestSetService(_db())
        with pytest.raises(ValueError, match="用例"):
            await svc.create_set("p1", "x", [])

    @pytest.mark.asyncio
    async def test_create_duplicate_name_raises(self):
        """同项目重名（唯一约束）——service 层查重抛错（比等 DB 约束报错友好）"""
        db = _db()

        async def _execute(q):
            r = MagicMock()
            r.scalar_one_or_none.return_value = MagicMock()  # 已存在同名
            return r
        db.execute = _execute

        svc = TestSetService(db)
        with pytest.raises(ValueError, match="已存在"):
            await svc.create_set("p1", "冒烟集", ["c1"])

    @pytest.mark.asyncio
    async def test_update_name_and_description(self):
        db = _db()
        ts = MagicMock()
        ts.name = "旧名"

        async def _get(cls, sid):
            return ts
        db.get = _get

        svc = TestSetService(db)
        await svc.update_set(str(uuid4()), {"name": "新名", "description": "描述"})
        assert ts.name == "新名"
        assert ts.description == "描述"

    @pytest.mark.asyncio
    async def test_update_unknown_field_raises(self):
        db = _db()
        ts = MagicMock()
        async def _get(cls, sid):
            return ts
        db.get = _get
        svc = TestSetService(db)
        with pytest.raises(ValueError, match="不可"):
            await svc.update_set(str(uuid4()), {"hack": 1})

    @pytest.mark.asyncio
    async def test_delete_set(self):
        db = _db()
        ts = MagicMock()
        async def _get(cls, sid):
            return ts
        db.get = _get
        db.delete = AsyncMock()

        svc = TestSetService(db)
        await svc.delete_set(str(uuid4()))
        db.delete.assert_awaited_once_with(ts)

    @pytest.mark.asyncio
    async def test_list_by_project(self):
        db = _db()
        rows = [MagicMock(), MagicMock()]
        db.execute = _exec(rows)
        svc = TestSetService(db)
        out = await svc.list_sets("p1")
        assert out == rows


class TestCaseManagement:
    @pytest.mark.asyncio
    async def test_add_cases_merges_dedup(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1"]

        async def _get(cls, sid):
            return ts
        db.get = _get

        svc = TestSetService(db)
        await svc.add_cases(str(uuid4()), ["c2", "c1"])
        assert sorted(ts.case_ids) == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_remove_case(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1", "c2"]

        async def _get(cls, sid):
            return ts
        db.get = _get

        svc = TestSetService(db)
        await svc.remove_case(str(uuid4()), "c1")
        assert ts.case_ids == ["c2"]

    @pytest.mark.asyncio
    async def test_remove_missing_case_noop(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1"]
        async def _get(cls, sid):
            return ts
        db.get = _get
        svc = TestSetService(db)
        await svc.remove_case(str(uuid4()), "nope")
        assert ts.case_ids == ["c1"]
