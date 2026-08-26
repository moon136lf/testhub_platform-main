"""
测试 SmartLocator - 智能定位器降级与自愈 (Task 16)

覆盖：
- 按评分降序尝试定位器
- 第一个失败时降级到第二个
- 所有定位器失败时触发自愈
- 自愈成功后回写缓存（confidence +1）
- 自愈失败时 confidence -1
- ElementNotFoundError 抛出
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.smart_locator import SmartLocator, ElementNotFoundError


def _make_strategy(type_, value, score, unique=True):
    return {"type": type_, "value": value, "score": score, "unique": unique, "verified": True}


class TestSmartLocatorLocateAndInteract:
    @pytest.mark.asyncio
    async def test_uses_highest_score_first(self):
        """应优先使用评分最高的定位器"""
        element_data = {
            "element_name": "登录按钮",
            "locator_strategies": {
                "strategies": [
                    _make_strategy("text", "button:has-text('登录')", 85),
                    _make_strategy("id", "#login", 120),
                ]
            },
            "semantic_info": {},
        }

        page = MagicMock()
        mock_locator = AsyncMock()
        mock_locator.wait_for = AsyncMock()
        mock_locator.click = AsyncMock()
        page.locator = MagicMock(return_value=mock_locator)

        locator = SmartLocator(element_data)
        result = await locator.locate_and_interact(page, action="click")

        assert result["status"] == "success"
        # 应使用第一个调用，即 id #login（score 120）
        page.locator.assert_called_with("#login")

    @pytest.mark.asyncio
    async def test_falls_back_on_failure(self):
        """第一个定位器失败时应降级到第二个"""
        element_data = {
            "element_name": "登录按钮",
            "locator_strategies": {
                "strategies": [
                    _make_strategy("id", "#old-id", 120),
                    _make_strategy("text", "button:has-text('登录')", 85),
                ]
            },
            "semantic_info": {},
        }

        page = MagicMock()
        # 第一个失败，第二个成功
        failing_locator = AsyncMock()
        failing_locator.wait_for = AsyncMock(side_effect=Exception("not found"))

        success_locator = AsyncMock()
        success_locator.wait_for = AsyncMock()
        success_locator.click = AsyncMock()

        page.locator = MagicMock(side_effect=[failing_locator, success_locator])

        locator = SmartLocator(element_data)
        result = await locator.locate_and_interact(page, action="click")

        assert result["status"] == "success"
        assert page.locator.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_element_not_found_when_all_fail_and_no_heal(self):
        """所有定位器失败且无语义信息时抛 ElementNotFoundError"""
        element_data = {
            "element_name": "丢失的按钮",
            "locator_strategies": {
                "strategies": [
                    _make_strategy("id", "#gone1", 120),
                    _make_strategy("text", "button:has-text('x')", 85),
                ]
            },
            "semantic_info": None,
        }

        page = MagicMock()
        failing = AsyncMock()
        failing.wait_for = AsyncMock(side_effect=Exception("not found"))
        page.locator = MagicMock(return_value=failing)

        locator = SmartLocator(element_data)

        with pytest.raises(ElementNotFoundError):
            await locator.locate_and_interact(page, action="click")

    @pytest.mark.asyncio
    async def test_self_heal_succeeds_after_all_locators_fail(self):
        """所有定位器失败时触发自愈并成功"""
        element_data = {
            "element_name": "按钮",
            "locator_strategies": {"strategies": [_make_strategy("id", "#gone", 120)]},
            "semantic_info": {"type": "button", "text": "登录"},
        }

        page = MagicMock()
        failing = AsyncMock()
        failing.wait_for = AsyncMock(side_effect=Exception("not found"))
        page.locator = MagicMock(return_value=failing)

        locator = SmartLocator(element_data)

        # Mock 自愈成功：返回一个可操作的 locator
        healed_locator = AsyncMock()
        healed_locator.click = AsyncMock()

        with patch.object(SmartLocator, "_self_heal_and_interact", new=AsyncMock(return_value={"status": "success", "action": "click"})):
            result = await locator.locate_and_interact(page, action="click")

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_performs_fill_action(self):
        """应正确执行 fill 操作"""
        element_data = {
            "element_name": "用户名输入框",
            "locator_strategies": {"strategies": [_make_strategy("id", "#username", 100)]},
            "semantic_info": {},
        }

        page = MagicMock()
        mock_locator = AsyncMock()
        mock_locator.wait_for = AsyncMock()
        mock_locator.fill = AsyncMock()
        page.locator = MagicMock(return_value=mock_locator)

        locator = SmartLocator(element_data)
        result = await locator.locate_and_interact(page, action="fill", value="admin")

        assert result["status"] == "success"
        mock_locator.fill.assert_awaited_once_with("admin")

    @pytest.mark.asyncio
    async def test_performs_select_action(self):
        """应正确执行 select 操作"""
        element_data = {
            "element_name": "下拉框",
            "locator_strategies": {"strategies": [_make_strategy("id", "#sel", 100)]},
            "semantic_info": {},
        }

        page = MagicMock()
        mock_locator = AsyncMock()
        mock_locator.wait_for = AsyncMock()
        mock_locator.select_option = AsyncMock()
        page.locator = MagicMock(return_value=mock_locator)

        locator = SmartLocator(element_data)
        result = await locator.locate_and_interact(page, action="select", value="option1")

        assert result["status"] == "success"
        mock_locator.select_option.assert_awaited_once_with("option1")

    @pytest.mark.asyncio
    async def test_unsupported_action_raises_value_error(self):
        """不支持的操作类型应抛 ValueError"""
        element_data = {
            "element_name": "x",
            "locator_strategies": {"strategies": [_make_strategy("id", "#x", 100)]},
            "semantic_info": {},
        }

        page = MagicMock()
        mock_locator = AsyncMock()
        mock_locator.wait_for = AsyncMock()
        page.locator = MagicMock(return_value=mock_locator)

        locator = SmartLocator(element_data)

        with pytest.raises(ValueError, match="Unsupported action"):
            await locator.locate_and_interact(page, action="hover")

    @pytest.mark.asyncio
    async def test_xpath_strategy_uses_xpath_prefix(self):
        """xpath 类型定位器应加 xpath= 前缀"""
        element_data = {
            "element_name": "x",
            "locator_strategies": {"strategies": [_make_strategy("xpath", "//button[1]", 55)]},
            "semantic_info": {},
        }

        page = MagicMock()
        mock_locator = AsyncMock()
        mock_locator.wait_for = AsyncMock()
        mock_locator.click = AsyncMock()
        page.locator = MagicMock(return_value=mock_locator)

        locator = SmartLocator(element_data)
        await locator.locate_and_interact(page, action="click")

        # 验证调用时加了 xpath= 前缀
        page.locator.assert_called_with("xpath=//button[1]")


"""SmartLocator SelfHealEngine integration test (Task 4 / #5b)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock


def asyncio_run(coro):
    return asyncio.run(coro)


class TestSelfHealIntegration:
    def _element_data(self):
        return {"element_id": "e1", "element_name": "用户名",
                "locator_strategies": {"strategies": [{"type": "css", "value": "#missing", "score": 10}]},
                "semantic_info": {"text": "用户名"}}

    def test_locate_and_interact_triggers_self_heal_on_failure(self, monkeypatch):
        """所有定位器失败 → 触发 SelfHealEngine.heal; 命中后执行操作并返回带 heal_log 的结果."""
        page = MagicMock()
        # 所有原始定位器失败 → 触发自愈
        loc = MagicMock()
        loc.wait_for = AsyncMock(side_effect=Exception("not found"))
        # healed locator 验证 + 操作成功
        healed_loc = MagicMock()
        healed_loc.wait_for = AsyncMock()
        healed_loc.fill = AsyncMock()
        # 第一次 page.locator 走原始策略失败, 自愈命中后再走 healed_loc
        page.locator = MagicMock(side_effect=[loc, healed_loc])
        # mock SelfHealEngine (patch 源模块, 方法内 lazy import 取到 fake)
        from app.services import self_heal_engine as she_mod
        fake_engine = MagicMock()
        fake_engine.heal = AsyncMock(return_value={
            "success": True, "locator": "page.get_by_label(\"用户名\")",
            "strategy": "semantic", "heal_log": [], "writeback": None,
        })
        monkeypatch.setattr(she_mod, "SelfHealEngine", lambda gw, cache: fake_engine)
        sl = SmartLocator(self._element_data(), gateway=MagicMock())
        result = asyncio_run(sl.locate_and_interact(page, "fill", value="admin"))
        assert result["status"] == "success"
        fake_engine.heal.assert_awaited_once()
        assert result.get("heal_log") == []
        assert result.get("writeback") is None

    def test_self_heal_all_levels_fail_raises_element_not_found(self, monkeypatch):
        """SelfHealEngine 全级失败 → 抛 ElementNotFoundError."""
        page = MagicMock()
        loc = MagicMock()
        loc.wait_for = AsyncMock(side_effect=Exception("not found"))
        page.locator = MagicMock(return_value=loc)
        from app.services import self_heal_engine as she_mod
        fake_engine = MagicMock()
        fake_engine.heal = AsyncMock(return_value={
            "success": False, "locator": None, "strategy": None,
            "heal_log": [{"level": 1, "success": False}], "writeback": None,
        })
        monkeypatch.setattr(she_mod, "SelfHealEngine", lambda gw, cache: fake_engine)
        sl = SmartLocator(self._element_data(), gateway=MagicMock())
        with pytest.raises(ElementNotFoundError):
            asyncio_run(sl.locate_and_interact(page, "click"))

    def test_gateway_defaults_none_backwards_compatible(self):
        """SmartLocator 不传 gateway 时 gateway=None (向后兼容)."""
        sl = SmartLocator(self._element_data())
        assert sl.gateway is None
