"""content 端点对绑定字段透传（方案V1 阶段4 Step 7）。"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.scripts import update_script_content
from app.schemas.script import ScriptContentUpdateRequest


@pytest.mark.asyncio
async def test_content_endpoint_passthrough_new_fields():
    """PUT /scripts/{id}/content 对 element_id/case_step_no/case_target_text/assertion_type 透传。"""
    captured = {}
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.to_dict = MagicMock(return_value={"id": str(asset.id)})

    async def fake_save(self, script_id, title, steps):
        captured["steps"] = steps
        return asset

    with patch("app.api.v1.scripts.ScriptEditService") as _:
        pass
    import app.api.v1.scripts as scripts_api
    with patch.object(scripts_api, "ScriptEditService") as MockSvc:
        MockSvc.return_value.save_steps = fake_save.__get__(MagicMock())
        req = ScriptContentUpdateRequest(
            title="t",
            steps=[{"seq": 1, "action": "input", "target": "#zh", "value": "v",
                    "element_name": "e", "expected": "",
                    "element_id": str(uuid.uuid4()), "case_step_no": 3,
                    "case_target_text": "账号输入框", "assertion_type": "expect_text"}],
        )
        resp = await update_script_content(str(asset.id), req, db=MagicMock())
    assert resp["code"] == 0
    s = captured["steps"][0]
    assert s["element_id"] and s["case_step_no"] == 3
    assert s["case_target_text"] == "账号输入框"
    assert s["assertion_type"] == "expect_text"
