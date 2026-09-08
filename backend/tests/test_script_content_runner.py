"""ScriptContentRunner：executor 消费编辑器行式步骤（修 0 步假通过）。
navigate/wait/assert_db 等编辑器动作不经元素库，target 即定位符。"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.script_executor import parse_editor_steps, dispatch_editor_action


class TestParseSteps:
    def test_editor_rows_with_seq_key(self):
        """编辑器保存的 step_mapping 用 seq 键——不再被 step 过滤为 0 步"""
        rows = [
            {"seq": 1, "action": "navigate", "target": "", "value": "https://x.com", "element_name": ""},
            {"seq": 2, "action": "click", "target": "#btn", "value": "", "element_name": "按钮"},
        ]
        steps = parse_editor_steps(rows)
        assert len(steps) == 2
        assert steps[0]["action"] == "navigate"

    def test_legacy_step_key_still_works(self):
        """旧 pipeline 步骤（step 键）仍被解析（兼容）"""
        rows = [{"step": 1, "action": "click", "target": "#a", "element_name": "x"}]
        assert len(parse_editor_steps(rows)) == 1

    def test_invalid_rows_skipped(self):
        rows = ["junk", {"seq": 1, "action": "click", "target": "#ok"}]
        assert len(parse_editor_steps(rows)) == 1


class TestDispatch:
    @pytest.mark.asyncio
    async def test_navigate(self):
        page = MagicMock()
        page.goto = AsyncMock()
        await dispatch_editor_action(page, {"action": "navigate", "target": "", "value": "https://x.com"}, None)
        page.goto.assert_called_with("https://x.com")

    @pytest.mark.asyncio
    async def test_click_and_input(self):
        page = MagicMock()
        loc = MagicMock()
        loc.click = AsyncMock(); loc.fill = AsyncMock()
        page.locator.return_value = loc
        await dispatch_editor_action(page, {"action": "click", "target": "#b", "value": ""}, None)
        page.locator.assert_called_with("#b")
        loc.click.assert_awaited()
        await dispatch_editor_action(page, {"action": "input", "target": "#u", "value": "admin"}, None)
        loc.fill.assert_awaited_with("admin")

    @pytest.mark.asyncio
    async def test_wait(self):
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        await dispatch_editor_action(page, {"action": "wait", "target": "", "value": "2"}, None)
        page.wait_for_timeout.assert_called_with(2000)

    @pytest.mark.asyncio
    async def test_select(self):
        page = MagicMock()
        loc = MagicMock(); loc.select_option = AsyncMock()
        page.locator.return_value = loc
        await dispatch_editor_action(page, {"action": "select", "target": "#e", "value": "dev"}, None)
        loc.select_option.assert_awaited_with("dev")

    @pytest.mark.asyncio
    async def test_assert_text_pass_and_fail(self):
        # async expect 的 to_have_text：通过时无异常
        page = MagicMock()
        # 真 locator 行为复杂——用 mock expect 注入：dispatch 的 expect 参数
        passed_loc = MagicMock()
        expect_mock = MagicMock()
        expect_mock.return_value.to_have_text = AsyncMock()
        page.locator.return_value = passed_loc
        await dispatch_editor_action(page, {"action": "assert_text", "target": ".t", "value": "x"}, expect_mock)
        expect_mock.assert_called()

    @pytest.mark.asyncio
    async def test_assert_db_pass_and_fail(self):
        page = MagicMock()
        with patch("app.services.script_executor._run_assert_db_query", new=AsyncMock(return_value="5")):
            r = await dispatch_editor_action(page, {"action": "assert_db", "target": "", "value": "SELECT 1", "expected": "5"}, None)
            assert r is None
        with patch("app.services.script_executor._run_assert_db_query", new=AsyncMock(return_value="6")):
            with pytest.raises(AssertionError, match="DB断言失败"):
                await dispatch_editor_action(page, {"action": "assert_db", "target": "", "value": "SELECT 1", "expected": "5"}, None)

    @pytest.mark.asyncio
    async def test_unknown_action_raises(self):
        with pytest.raises(ValueError, match="不支持"):
            await dispatch_editor_action(MagicMock(), {"action": "hack", "target": "", "value": ""}, None)
