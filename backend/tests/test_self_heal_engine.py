"""Self-heal engine tests (mock page/LLM/cache)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.self_heal_engine import SelfHealEngine


def asyncio_run(coro): return asyncio.run(coro)


class FakeEl:
    """模拟 Playwright ElementHandle."""
    def __init__(self, text="", aria="", visible=True):
        self._text = text; self._aria = aria; self._visible = visible
    async def text_content(self): return self._text
    async def get_attribute(self, name): return self._aria if name == "aria-label" else None
    async def is_visible(self): return self._visible


class FakePage:
    def __init__(self, elements):
        self._elements = elements  # dict selector -> [FakeEl]
    async def query_selector_all(self, selector):
        return self._elements.get(selector, [])


class FakeCache:
    def __init__(self): self.calls = []
    async def record_heal_success(self, eid, info): self.calls.append(("success", eid, info)); return 1
    async def record_heal_failure(self, eid): self.calls.append(("failure", eid))
    async def should_writeback_to_repo(self, eid): return False
    async def get_writeback_locator(self, eid): return None


class TestHealByDomFuzz:
    def _element_data(self):
        return {"element_id": "e1", "element_name": "用户名",
                "locator_strategies": {"strategies": []}, "semantic_info": {"text": "用户名"}}

    def test_dom_fuzz_matches_high_score(self):
        page = FakePage({"input": [FakeEl(text="用户名", aria="用户名")]})
        gw = MagicMock()
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_dom_fuzz(page, self._element_data()))
        # score 应 >= 70, 命中返回定位器
        assert result is not None

    def test_dom_fuzz_no_match_returns_none(self):
        page = FakePage({"input": [FakeEl(text="完全不相关的东西")]})
        gw = MagicMock()
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_dom_fuzz(page, self._element_data()))
        assert result is None


class TestHealByAiDom:
    def _element_data(self):
        return {"element_id": "e1", "element_name": "登录按钮",
                "locator_strategies": {"strategies": []}, "semantic_info": {"text": "登录"}}

    def test_ai_dom_returns_locator_from_llm(self):
        page = MagicMock()
        page.content = AsyncMock(return_value="<html><button>登录</button></html>")
        loc = MagicMock()
        loc.wait_for = AsyncMock()
        page.locator = MagicMock(return_value=loc)
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "page.get_by_role(\"button\", name=\"登录\")", "tokens": 50})
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_ai_dom(page, self._element_data()))
        assert result == "page.get_by_role(\"button\", name=\"登录\")"

    def test_ai_dom_invalid_locator_returns_none(self):
        page = MagicMock()
        page.content = AsyncMock(return_value="<html></html>")
        loc = MagicMock()
        loc.wait_for = AsyncMock(side_effect=Exception("not found"))
        page.locator = MagicMock(return_value=loc)
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "page.bogus()", "tokens": 10})
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_ai_dom(page, self._element_data()))
        assert result is None
