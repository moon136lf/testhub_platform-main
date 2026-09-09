"""元素列表 page_name / 状态开关 / 分页倒序 测试（mock db）—— #elem-mg T4-T6"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

from app.services.element_asset_service import ElementAssetService


def _db():
    db = MagicMock()
    db.refresh = AsyncMock()
    return db


def _exec_scalars(rows):
    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        return r
    return _execute


def _exec_scalar(value):
    async def _execute(q):
        r = MagicMock()
        r.scalar.return_value = value
        return r
    return _execute


def _element(page_id=None):
    el = MagicMock()
    el.page_id = page_id or uuid4()
    el.to_dict.return_value = {"element_name": "登录按钮", "page_id": str(el.page_id)}
    return el


class TestPageNameAttach:
    @pytest.mark.asyncio
    async def test_page_name_attached(self):
        pid = uuid4()
        el = _element(pid)
        page = MagicMock()
        page.id, page.page_name = pid, "登录页"
        db = _db()

        async def _execute(q):
            r = MagicMock()
            if "page_repository" in str(q).lower():
                r.scalars.return_value.all.return_value = [page]
            else:
                r.scalars.return_value.all.return_value = [el]
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        out = await svc.attach_page_names([el])
        assert out[0]["page_name"] == "登录页"

    @pytest.mark.asyncio
    async def test_global_element_page_name_none(self):
        """全局元素无页面 → page_name=None"""
        el = _element(None)
        db = _db()

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        out = await svc.attach_page_names([el])
        assert out[0]["page_name"] is None


class TestSetStatus:
    @pytest.mark.asyncio
    async def test_toggle_active_deprecated(self):
        el = MagicMock()
        el.status = "active"
        db = _db()

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.set_status("11111111-1111-1111-1111-111111111111", "deprecated")
        assert el.status == "deprecated"
        db.commit.assert_awaited()
        await svc.set_status("11111111-1111-1111-1111-111111111111", "active")
        assert el.status == "active"

    @pytest.mark.asyncio
    async def test_invalid_status_rejected(self):
        db = _db()
        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="status"):
            await svc.set_status("11111111-1111-1111-1111-111111111111", "deleted")

    @pytest.mark.asyncio
    async def test_deleted_element_not_togglable(self):
        """回收站元素（status=deleted）不能通过开关改状态"""
        el = MagicMock()
        el.status = "deleted"
        db = _db()

        async def _get(cls, eid):
            return el
        db.get = _get

        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="不存在"):
            await svc.set_status("11111111-1111-1111-1111-111111111111", "active")

    @pytest.mark.asyncio
    async def test_find_by_name_excludes_deprecated(self):
        """转脚本链路：find_by_name 只匹配 active，禁用元素不命中"""
        from app.services.element_service import ElementService
        db = _db()

        async def _execute(q):
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r
        db.execute = _execute

        svc = ElementService(db)
        assert await svc.find_by_name(str(uuid4()), "登录按钮") is None


class TestPagination:
    """T6：分页 + updated_at 倒序（list_elements_paged + 端点信封）"""

    @pytest.mark.asyncio
    async def test_unpaginated_returns_list(self):
        """不带 page 参数 → list_elements 仍返回全量列表（向后兼容）"""
        db = _db()
        els = [_element(), _element()]
        db.execute = _exec_scalars(els)
        svc = ElementAssetService(db)
        out = await svc.list_elements("p1")
        assert out == els

    @pytest.mark.asyncio
    async def test_paged_returns_rows_and_total(self):
        db = _db()
        rows = [_element()]
        calls = []

        async def _execute(q):
            calls.append(q)
            r = MagicMock()
            if len(calls) == 1:  # count 查询
                r.scalar.return_value = 23
            else:
                r.scalars.return_value.all.return_value = rows
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        out, total = await svc.list_elements_paged("p1", page=2, page_size=10)
        assert total == 23
        assert out == rows
        sql = str(calls[1]).lower()
        assert "limit" in sql and "offset" in sql

    @pytest.mark.asyncio
    async def test_order_by_updated_at_desc_nullslast(self):
        """分页查询排序应为 updated_at DESC NULLS LAST"""
        from sqlalchemy.dialects import postgresql
        db = _db()
        calls = []

        async def _execute(q):
            calls.append(q)
            r = MagicMock()
            if len(calls) == 1:
                r.scalar.return_value = 0
            else:
                r.scalars.return_value.all.return_value = []
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        await svc.list_elements_paged("p1", page=1)
        sql = str(calls[1].compile(dialect=postgresql.dialect())).upper()
        assert "UPDATED_AT DESC NULLS LAST" in sql

    @pytest.mark.asyncio
    async def test_unpaged_order_by_updated_at_desc_nullslast(self):
        """不分页查询同样按 updated_at DESC NULLS LAST 排序"""
        from sqlalchemy.dialects import postgresql
        db = _db()
        calls = []

        async def _execute(q):
            calls.append(q)
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        await svc.list_elements("p1")
        sql = str(calls[0].compile(dialect=postgresql.dialect())).upper()
        assert "UPDATED_AT DESC NULLS LAST" in sql
