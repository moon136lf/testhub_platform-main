"""定位器选择核心逻辑：score 降序选首选 + 类型词表归一 + fallback 链"""
import pytest
from app.services.element_service import (
    normalize_strategies,
    select_primary_locator,
    build_fallback_chain,
    strategy_to_playwright,
)


class TestNormalize:
    def test_fills_missing_score_with_type_baseline(self):
        # 旧数据无 score：按类型基准分补齐
        sts = [{"type": "css", "value": ".btn"}]
        out = normalize_strategies(sts)
        assert out[0]["score"] == 70  # css 基准 70

    def test_fills_missing_unique_verified(self):
        sts = [{"type": "id", "value": "#a", "score": 100}]
        out = normalize_strategies(sts)
        assert out[0]["unique"] is False
        assert out[0]["verified"] is False

    def test_sorts_by_score_desc(self):
        sts = [
            {"type": "css", "value": ".a", "score": 60, "unique": True, "verified": True},
            {"type": "id", "value": "#b", "score": 90, "unique": True, "verified": True},
        ]
        out = normalize_strategies(sts)
        assert out[0]["value"] == "#b"

    def test_unknown_type_gets_lowest_baseline(self):
        out = normalize_strategies([{"type": "weird", "value": "x"}])
        assert out[0]["score"] == 30

    def test_skips_invalid_entries(self):
        out = normalize_strategies([{"type": "css"}, "junk", None, {"type": "id", "value": "#ok"}])
        assert len(out) == 1 and out[0]["value"] == "#ok"


class TestSelectPrimary:
    def test_returns_highest_score_value(self):
        sts = [
            {"type": "css", "value": ".a", "score": 60, "unique": True, "verified": True},
            {"type": "id", "value": "#b", "score": 90, "unique": True, "verified": True},
        ]
        assert select_primary_locator(sts) == "#b"

    def test_returns_none_when_empty(self):
        assert select_primary_locator([]) is None
        assert select_primary_locator(None) is None


class TestFallbackChain:
    def test_chain_in_score_order_excluding_primary(self):
        sts = [
            {"type": "text", "value": "提交", "score": 80, "unique": True, "verified": True},
            {"type": "id", "value": "#submit", "score": 100, "unique": True, "verified": True},
            {"type": "css", "value": ".s", "score": 70, "unique": True, "verified": True},
        ]
        assert build_fallback_chain(sts) == ["提交", ".s"]  # 降序，去掉首选 #submit

    def test_empty_chain_when_single(self):
        assert build_fallback_chain([{"type": "id", "value": "#x", "score": 100}]) == []


class TestToPlaywright:
    """类型词表统一（对齐生成端 playwright_locator_core）：id/data-testid/name/role-text/text/class-type/css/xpath"""

    def test_css(self):
        assert strategy_to_playwright({"type": "css", "value": ".btn"}) == 'page.locator(".btn")'

    def test_id_maps_to_css(self):
        assert strategy_to_playwright({"type": "id", "value": "#submit"}) == 'page.locator("#submit")'

    def test_class_type_maps_to_css(self):
        assert strategy_to_playwright({"type": "class-type", "value": "input.form-control"}) == 'page.locator("input.form-control")'

    def test_data_testid(self):
        assert strategy_to_playwright(
            {"type": "data-testid", "value": "[data-testid='save']"}
        ) == "page.locator([data-testid='save'])"

    def test_text(self):
        assert strategy_to_playwright({"type": "text", "value": "提交"}) == 'page.get_by_text("提交")'

    def test_role_text_uses_name_kwarg(self):
        # role-text 的 value 形如 "button[role='button']:has-text('提交')"
        loc = strategy_to_playwright({"type": "role-text", "value": "button[role='button']:has-text('提交')"})
        assert 'get_by_role' in loc and '提交' in loc

    def test_name_attr(self):
        assert strategy_to_playwright({"type": "name", "value": "[name='username']"}) == "page.locator([name='username'])"

    def test_xpath_prefixed(self):
        assert strategy_to_playwright({"type": "xpath", "value": "//div[1]"}) == 'page.locator("xpath=//div[1]")'

    def test_unsupported_type_returns_none(self):
        assert strategy_to_playwright({"type": "label", "value": "x"}) is None
        assert strategy_to_playwright({"type": "css", "value": ""}) is None

    def test_role_text_malformed_returns_none(self):
        # 正则不匹配的畸形 role-text value
        assert strategy_to_playwright({"type": "role-text", "value": "garbage[[["}) is None


class TestFindFallback:
    """ElementLocatorLookup.find 对转换失败策略的回退"""

    def _fake_svc(self, el):
        import asyncio
        from unittest.mock import MagicMock
        svc = MagicMock()
        svc.find_by_name = MagicMock(side_effect=None)
        async def _find(*a, **k):
            return el
        svc.find_by_name = _find
        return svc

    def test_falls_back_when_primary_unconvertible(self):
        import asyncio
        from unittest.mock import MagicMock
        from app.services.element_service import ElementLocatorLookup

        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "label", "value": "用户名", "score": 100},
            {"type": "css", "value": ".username-input", "score": 70},
        ]}
        lookup = ElementLocatorLookup(self._fake_svc(el))
        result = asyncio.run(lookup.find("p1", "用户名"))
        assert result == 'page.locator(".username-input")'

    def test_returns_none_when_all_unconvertible(self):
        import asyncio
        from unittest.mock import MagicMock
        from app.services.element_service import ElementLocatorLookup

        el = MagicMock()
        el.locator_strategies = [{"type": "label", "value": "x"}]
        lookup = ElementLocatorLookup(self._fake_svc(el))
        assert asyncio.run(lookup.find("p1", "x")) is None
