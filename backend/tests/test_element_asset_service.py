"""ElementAssetService 测试（mock db）—— 阶段1 引用计数 + CRUD/调序/回收站"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime as _dt

from app.services.element_asset_service import ElementAssetService


def _db():
    return MagicMock()


def _script(step_element_names):
    s = MagicMock()
    s.step_mapping = [{"element_name": n} for n in step_element_names]
    return s


def _exec_return(rows):
    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        return r
    return _execute


class TestRefCount:
    @pytest.mark.asyncio
    async def test_counts_scripts_referencing_element(self):
        db = _db()
        scripts = [
            _script(["登录按钮", "用户名输入框"]),
            _script(["登录按钮"]),
            _script(["其他元素"]),
        ]
        db.execute = _exec_return(scripts)

        svc = ElementAssetService(db)
        n = await svc.count_references("p1", "登录按钮")
        assert n == 2

    @pytest.mark.asyncio
    async def test_one_script_counts_once_even_with_multiple_steps(self):
        """同一脚本多步骤引用同一元素，只计 1 次"""
        db = _db()
        scripts = [_script(["登录按钮", "登录按钮", "登录按钮"])]
        db.execute = _exec_return(scripts)

        svc = ElementAssetService(db)
        assert await svc.count_references("p1", "登录按钮") == 1

    @pytest.mark.asyncio
    async def test_empty_name_returns_zero(self):
        db = _db()
        db.execute = _exec_return([])
        svc = ElementAssetService(db)
        assert await svc.count_references("p1", "") == 0
        assert await svc.count_references("p1", None) == 0

    @pytest.mark.asyncio
    async def test_ignores_malformed_step_mapping(self):
        db = _db()
        s = MagicMock()
        s.step_mapping = ["not-a-dict", {"other": 1}, {"element_name": "目标元素"}]
        db.execute = _exec_return([s])
        svc = ElementAssetService(db)
        assert await svc.count_references("p1", "目标元素") == 1

    @pytest.mark.asyncio
    async def test_zero_when_no_scripts(self):
        db = _db()
        db.execute = _exec_return([])
        svc = ElementAssetService(db)
        assert await svc.count_references("p1", "x") == 0


class TestListReferringScripts:
    @pytest.mark.asyncio
    async def test_lists_script_id_and_name(self):
        db = _db()
        s1, s2 = _script(["a"]), _script(["b"])
        s1.id, s1.name = uuid4(), "脚本A"
        s2.id, s2.name = uuid4(), "脚本B"
        db.execute = _exec_return([s1, s2])

        svc = ElementAssetService(db)
        refs = await svc.list_referring_scripts("p1", "a")
        assert [x["name"] for x in refs] == ["脚本A"]
        assert str(s1.id) == refs[0]["id"]

    @pytest.mark.asyncio
    async def test_list_empty_name_returns_empty(self):
        db = _db()
        db.execute = _exec_return([])
        svc = ElementAssetService(db)
        assert await svc.list_referring_scripts("p1", "") == []
        assert await svc.list_referring_scripts("p1", None) == []

    @pytest.mark.asyncio
    async def test_empty_when_none_reference(self):
        db = _db()
        db.execute = _exec_return([])
        svc = ElementAssetService(db)
        assert await svc.list_referring_scripts("p1", "x") == []


class TestElementCRUD:
    @pytest.mark.asyncio
    async def test_update_element_name(self):
        db = _db()
        el = MagicMock()
        el.element_name = "旧名"

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.update_element(str(uuid4()), {"element_name": "新名"})
        assert el.element_name == "新名"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_rejects_unknown_field(self):
        db = _db()
        el = MagicMock()

        async def _get(cls, eid):
            return el
        db.get = _get
        svc = ElementAssetService(db)
        with pytest.raises(ValueError):
            await svc.update_element(str(uuid4()), {"hack_field": "x"})

    @pytest.mark.asyncio
    async def test_update_missing_element_raises(self):
        db = _db()

        async def _get(cls, eid):
            return None
        db.get = _get
        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="不存在"):
            await svc.update_element(str(uuid4()), {"element_name": "x"})


class TestReorder:
    @pytest.mark.asyncio
    async def test_reorder_down_swaps_and_rescores(self):
        """调序 = 相邻交换，score 跟随位置重排（150-pos*10），排序即置信度"""
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "id", "value": "#a", "score": 100, "unique": True, "verified": True},
            {"type": "css", "value": ".b", "score": 80, "unique": True, "verified": True},
        ]}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.reorder_locator(str(uuid4()), 0, "down")
        sts = el.locator_strategies["strategies"]
        assert sts[0]["value"] == ".b"   # css 升到第一
        assert sts[0]["score"] == 150    # score 跟随位置
        assert sts[1]["value"] == "#a" and sts[1]["score"] == 140

    @pytest.mark.asyncio
    async def test_reorder_up(self):
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "id", "value": "#a", "score": 150, "unique": True, "verified": True},
            {"type": "css", "value": ".b", "score": 140, "unique": True, "verified": True},
            {"type": "text", "value": "t", "score": 130, "unique": True, "verified": True},
        ]}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.reorder_locator(str(uuid4()), 2, "up")  # 最后一条上移
        sts = el.locator_strategies["strategies"]
        assert [s["value"] for s in sts] == ["#a", "t", ".b"]

    @pytest.mark.asyncio
    async def test_reorder_at_boundary_is_noop(self):
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "id", "value": "#a", "score": 150, "unique": True, "verified": True},
        ]}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reorder_index_out_of_range_noop(self):
        """index 越界（schema 只约束 ge=0），up/down 都静默不 commit"""
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "id", "value": "#a", "score": 150, "unique": True, "verified": True},
        ]}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        for direction in ("up", "down"):
            el.locator_strategies = {"strategies": [
                {"type": "id", "value": "#a", "score": 150, "unique": True, "verified": True},
            ]}
            await svc.reorder_locator(str(uuid4()), 5, direction)
        assert el.locator_strategies["strategies"][0]["value"] == "#a"
        db.commit.assert_not_awaited()


class TestAddLocator:
    @pytest.mark.asyncio
    async def test_add_custom_locator(self):
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": []}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.add_locator(str(uuid4()), "css", ".my-custom", score=50)
        sts = el.locator_strategies["strategies"]
        assert len(sts) == 1
        assert sts[0]["value"] == ".my-custom"
        assert sts[0]["source"] == "manual"
        assert sts[0]["unique"] is False

    @pytest.mark.asyncio
    async def test_add_locator_empty_value_raises(self):
        db = _db()
        svc = ElementAssetService(db)
        with pytest.raises(ValueError):
            await svc.add_locator(str(uuid4()), "css", "  ")


class TestRecycleBin:
    @pytest.mark.asyncio
    async def test_soft_delete_sets_recycled_at(self):
        db = _db()
        el = MagicMock()
        el.status = "active"

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.recycle_element(str(uuid4()))
        assert el.status == "deleted"
        assert el.recycled_at is not None

    @pytest.mark.asyncio
    async def test_restore_from_recycle(self):
        db = _db()
        el = MagicMock()
        el.status = "deleted"
        el.recycled_at = _dt(2026, 9, 1)

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.restore_element(str(uuid4()))
        assert el.status == "active"
        assert el.recycled_at is None

    @pytest.mark.asyncio
    async def test_list_recycled_filters_project_and_deleted(self):
        db = _db()
        els = [MagicMock(), MagicMock()]
        db.execute = _exec_return(els)

        svc = ElementAssetService(db)
        out = await svc.list_recycled("p1")
        assert out == els
