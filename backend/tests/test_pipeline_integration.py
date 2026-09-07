# backend/tests/test_pipeline_integration.py
"""Pipeline + element lookup adapter integration."""
import asyncio
import pytest
from app.services.script_pipeline import step3_match_locators, ActionIntent
from app.services.element_service import ElementLocatorLookup


class FakeElementService:
    def __init__(self, mapping):
        self.mapping = mapping

    async def find_by_name(self, project_id: str, element_name: str):
        return self.mapping.get(element_name)


class TestElementLocatorLookup:
    def test_adapter_returns_locator_string(self):
        fake = FakeElementService({"用户名": type("El", (), {
            "locator_strategies": [{"type": "text", "value": "用户名", "score": 80}]})()})
        lookup = ElementLocatorLookup(fake)
        result = asyncio.run(step3_match_locators(
            [ActionIntent(step=1, action="fill", target="用户名", value="admin")],
            "p1", lookup, ai_optimize=False, gateway=None))
        assert result[0].locator == 'page.get_by_text("用户名")'
        assert result[0].locator_status == "matched"
