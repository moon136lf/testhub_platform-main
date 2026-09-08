"""ScriptContentRunner：executor 消费编辑器行式步骤（修 0 步假通过）。
navigate/wait/assert_db 等编辑器动作不经元素库，target 即定位符。"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.script_executor import parse_editor_steps, dispatch_editor_action


from app.services.script_executor import ScriptExecutor
from app.models.test_case import ScriptAsset
from app.models.execution import ExecutionRecord


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
    async def test_assert_text_pass(self):
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
    async def test_assert_text_fail(self):
        """to_have_text 抛 AssertionError → 断言失败上抛"""
        page = MagicMock()
        expect_mock = MagicMock()
        expect_mock.return_value.to_have_text = AsyncMock(side_effect=AssertionError("expect"))
        with pytest.raises(AssertionError):
            await dispatch_editor_action(page, {"action": "assert_text", "target": ".t", "value": "x"}, expect_mock)

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


class TestAssertDbReadOnlyGuard:
    @pytest.mark.asyncio
    async def test_assert_db_read_only_guard(self):
        """UPDATE 语句被只读事务拒绝"""
        # AsyncSessionLocal 在 _run_assert_db_query 内延迟导入 → patch 源头 app.core.database
        with patch("app.core.database.AsyncSessionLocal") as mock_session_cls:
            mock_db = MagicMock()
            mock_db.execute = AsyncMock(side_effect=[
                MagicMock(),  # SET TRANSACTION 成功
                Exception("cannot execute UPDATE in a read-only transaction"),
            ])
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_db
            with pytest.raises(Exception, match="read-only"):
                from app.services.script_executor import _run_assert_db_query
                await _run_assert_db_query("UPDATE x SET y=1")


class FakeSSE:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kw):
        self.messages.append(kw)


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


class TestExecuteEditorBranch:
    """executor.execute() 的编辑器分支集成测试（mock page）"""

    def _build(self, step_mapping, max_failures=8):
        sa = ScriptAsset(
            id="s1", case_id="c1", project_id="p1", name="编辑器脚本",
            content="", version=1, status="confirmed", category="uncategorized",
            step_mapping=step_mapping, locator_source="manual",
            last_status="never_run", run_count=0,
        )
        gw = MagicMock(); gw.tokens = 0
        storage = MagicMock(); storage.upload_bytes = AsyncMock(return_value="/static/f.png")
        element_svc = MagicMock(); element_svc.find_by_name = AsyncMock(return_value=None)
        svc = ScriptExecutor(db=MagicMock(), gateway=gw, storage=storage, element_svc=element_svc)
        page = MagicMock()
        page.goto = AsyncMock()
        page.close = AsyncMock()
        page.content = AsyncMock(return_value="<html>x</html>")
        page.screenshot = AsyncMock(return_value=b"png")
        loc = MagicMock()
        loc.click = AsyncMock()
        loc.fill = AsyncMock()
        page.locator.return_value = loc
        sse = FakeSSE()
        er = ExecutionRecord(id="er1", exec_id="exec-1", project_id="p1",
                             exec_type="single", status="running", total_cases=1)
        config = MagicMock(headless=True, timeout=60, max_failures=max_failures)
        return sa, svc, page, loc, sse, er, config, storage

    @pytest.mark.asyncio
    async def test_execute_editor_format_runs_dispatch(self):
        """编辑器格式 step_mapping（seq 键）→ execute 走编辑器分支"""
        sa, svc, page, loc, sse, er, config, storage = self._build([
            {"seq": 1, "action": "navigate", "target": "", "value": "https://x.com"},
            {"seq": 2, "action": "click", "target": "#btn", "value": ""},
        ])
        detail = await svc.execute(sa, config=config, target_url="http://x",
                                         sse=sse, execution_record=er, page=page)
        page.goto.assert_awaited_with("https://x.com")
        page.locator.assert_called_with("#btn")
        loc.click.assert_awaited()
        assert detail.status == "pass"
        assert sa.last_status == "passed"
        assert sa.run_count == 1

    @pytest.mark.asyncio
    async def test_execute_editor_format_failure_collection(self):
        """一条成功一条失败（click 抛异常）→ detail/last_failure 计数对齐、截图采集被调用"""
        sa, svc, page, loc, sse, er, config, storage = self._build([
            {"seq": 1, "action": "navigate", "target": "", "value": "https://x.com"},
            {"seq": 2, "action": "click", "target": "#btn", "value": ""},
        ])
        loc.click = AsyncMock(side_effect=Exception("boom"))
        detail = await svc.execute(sa, config=config, target_url="http://x",
                                         sse=sse, execution_record=er, page=page)
        assert detail.status == "fail"
        assert detail.error_msg and "boom" in detail.error_msg
        assert detail.screenshot_url == "/static/f.png"
        storage.upload_bytes.assert_awaited()
        assert sa.last_status == "failed"

    @pytest.mark.asyncio
    async def test_execute_editor_format_max_failures_break(self):
        """max_failures=2，连续 3 条失败 → 第 3 条不执行"""
        sa, svc, page, loc, sse, er, config, storage = self._build([
            {"seq": 1, "action": "click", "target": "#a", "value": ""},
            {"seq": 2, "action": "click", "target": "#b", "value": ""},
            {"seq": 3, "action": "click", "target": "#c", "value": ""},
        ], max_failures=2)
        loc.click = AsyncMock(side_effect=Exception("boom"))
        detail = await svc.execute(sa, config=config, target_url="http://x",
                                         sse=sse, execution_record=er, page=page)
        assert detail.status == "fail"
        assert loc.click.await_count == 2  # 第 3 条未执行
