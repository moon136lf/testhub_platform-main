"""脚本编辑保存：PUT /scripts/{id}/content（步骤化编辑器保存链路）"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4

from app.services.script_edit_service import ScriptEditService


def _db():
    db = MagicMock()
    db.commit = AsyncMock()
    return db


class TestSaveSteps:
    @pytest.mark.asyncio
    async def test_save_generates_content_and_bumps_version(self):
        db = _db()
        asset = MagicMock()
        asset.name = "登录脚本"
        asset.content = "旧代码"
        asset.version = 1
        asset.step_mapping = []

        async def _get(cls, sid):
            return asset
        db.get = _get

        svc = ScriptEditService(db)
        steps = [
            {"seq": 1, "action": "navigate", "target": "", "value": "https://x.com", "element_name": ""},
            {"seq": 2, "action": "click", "target": "#btn", "value": "", "element_name": "按钮"},
        ]
        result = await svc.save_steps(str(uuid4()), "登录脚本V2", steps)
        assert "page.goto" in asset.content
        assert 'page.locator("#btn").click()' in asset.content
        assert asset.version == 2           # 1+1
        assert asset.step_mapping == steps  # 原始行存回 step_mapping
        assert result is asset
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_save_missing_script_raises(self):
        db = _db()

        async def _get(cls, sid):
            return None
        db.get = _get
        svc = ScriptEditService(db)
        with pytest.raises(ValueError, match="不存在"):
            await svc.save_steps(str(uuid4()), "t", [{"seq": 1, "action": "wait", "target": "", "value": "1"}])

    @pytest.mark.asyncio
    async def test_save_empty_steps_raises(self):
        db = _db()
        asset = MagicMock()
        async def _get(cls, sid):
            return asset
        db.get = _get
        svc = ScriptEditService(db)
        with pytest.raises(ValueError):
            await svc.save_steps(str(uuid4()), "t", [])

    @pytest.mark.asyncio
    async def test_save_invalid_action_propagates(self):
        """codegen 的 ValueError（未知操作）原样上抛——API 层转 400"""
        db = _db()
        asset = MagicMock()
        async def _get(cls, sid):
            return asset
        db.get = _get
        svc = ScriptEditService(db)
        with pytest.raises(ValueError, match="不支持"):
            await svc.save_steps(str(uuid4()), "t", [{"seq": 1, "action": "hack", "target": "", "value": ""}])

    @pytest.mark.asyncio
    async def test_save_empty_title_falls_back_to_asset_name(self):
        db = _db()
        asset = MagicMock()
        asset.name = "原名"
        async def _get(cls, sid):
            return asset
        db.get = _get
        svc = ScriptEditService(db)
        await svc.save_steps(str(uuid4()), "", [{"seq": 1, "action": "wait", "target": "", "value": "1"}])
        # title 空则用 asset.name（生成脚本 docstring 里应含原名）
        assert "原名" in asset.content
