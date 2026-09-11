"""元素管理批量修复测试（问题4/9/10/12 + 问题2 视口坐标 + 问题8 verify 桥接）

mock db 模式（对齐 test_element_asset_service.py）。
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4
from datetime import datetime as _dt

from app.services.element_asset_service import ElementAssetService


def _db():
    return MagicMock()


def _exec_return(rows):
    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        return r
    return _execute


# ---------------- 问题12：回收站倒序 ----------------

class TestListRecycledSorted:
    @pytest.mark.asyncio
    async def test_list_recycled_orders_by_recycled_at_desc(self):
        """问题12：list_recycled 查询应带 recycled_at 倒序"""
        db = _db()
        captured = {}

        async def _execute(q):
            captured["q"] = q
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        await svc.list_recycled("p1")
        q = str(captured["q"])
        assert "recycled_at" in q
        assert "DESC" in q.upper()


# ---------------- 问题10：回收站附 page_name ----------------

class TestRecycleBinPageName:
    @pytest.mark.asyncio
    async def test_recycle_bin_attaches_page_names(self):
        """问题10：recycle_bin 端点返回 attach_page_names 结果"""
        from app.api.v1.elements import recycle_bin
        els = [MagicMock()]
        with patch("app.api.v1.elements.ElementAssetService") as mock_svc_cls, \
             patch("app.api.v1.elements.Query", return_value="p1"):
            mock_svc = mock_svc_cls.return_value
            mock_svc.list_recycled = AsyncMock(return_value=els)
            expected = [{"id": "e1", "page_name": "页面A"}]
            mock_svc.attach_page_names = AsyncMock(return_value=expected)
            out = await recycle_bin(project_id="p1", db=_db())
        assert out["data"] == expected
        mock_svc.attach_page_names.assert_awaited_once_with(els)
