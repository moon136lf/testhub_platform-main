"""ElementAssetService 测试（mock db）—— 阶段1 引用计数部分"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4

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
