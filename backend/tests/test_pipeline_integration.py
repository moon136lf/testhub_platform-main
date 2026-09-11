# backend/tests/test_pipeline_integration.py
"""Pipeline + element find_candidates 协议集成。"""
import asyncio
import pytest
from app.services.script_pipeline import step3_match_locators, ActionIntent


class FakeElementService:
    def __init__(self, mapping):
        self.mapping = mapping

    async def find_candidates(self, project_id, target, intent_action=None, page_id=None):
        if target not in self.mapping:
            return []
        return [{"element_id": "el-1", "element_name": target,
                 "locator": self.mapping[target], "confidence": 5,
                 "score": 1.0, "match_level": "L1"}]


class TestFindCandidatesProtocol:
    def test_candidates_hit_binds_locator(self):
        fake = FakeElementService({"用户名": 'page.get_by_text("用户名")'})
        result = asyncio.run(step3_match_locators(
            [ActionIntent(step=1, action="fill", target="用户名", value="admin")],
            "p1", fake, ai_optimize=False, gateway=None))
        assert result[0].locator == 'page.get_by_text("用户名")'
        assert result[0].locator_status == "matched"
        assert result[0].locator_source == "element_library"
        assert result[0].element_id == "el-1"
