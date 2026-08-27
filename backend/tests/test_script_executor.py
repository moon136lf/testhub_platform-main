"""Script executor tests (mock Playwright/SmartLocator/Storage)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.script_executor import classify_error, collect_failure
from app.services.smart_locator import ElementNotFoundError


def asyncio_run(coro):
    return asyncio.run(coro)


class TestClassifyError:
    def test_locate_failed(self):
        assert classify_error(ElementNotFoundError("x")) == "locate_failed"

    def test_timeout(self):
        assert classify_error(asyncio.TimeoutError()) == "timeout"

    def test_assertion_failed(self):
        assert classify_error(AssertionError("exp got act")) == "assertion_failed"

    def test_script_error(self):
        assert classify_error(ValueError("bad json")) == "script_error"


class TestCollectFailure:
    def test_collects_screenshot_dom_stack(self):
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=b"png-bytes")
        page.content = AsyncMock(return_value="<html>dom</html>")
        storage = MagicMock()
        storage.upload_bytes = AsyncMock(return_value="/static/fail_1.png")
        failure = asyncio_run(collect_failure(page, step=1, error=ValueError("boom"), storage=storage))
        assert failure["error_type"] == "script_error"
        assert failure["screenshot_url"] == "/static/fail_1.png"
        assert failure["dom_snapshot"] == "<html>dom</html>"
        assert "ValueError" in failure["stack_trace"]
        assert "boom" in failure["error_msg"]

    def test_collect_failure_browser_closed_graceful(self):
        page = MagicMock()
        page.screenshot = AsyncMock(side_effect=Exception("browser closed"))
        page.content = AsyncMock(side_effect=Exception("browser closed"))
        failure = asyncio_run(collect_failure(page, step=2, error=ElementNotFoundError("x")))
        assert failure["error_type"] == "locate_failed"
        assert failure["screenshot_url"] is None
        assert failure["dom_snapshot"] is None
        # stack_trace 仍有（来自 error 实例自身）
        assert failure["stack_trace"] is not None


from app.services.script_executor import ScriptExecutor
from app.models.test_case import ScriptAsset
from app.models.execution import ExecutionRecord


class FakeSmartLocator:
    def __init__(self, element_data, fail_on_step=None):
        self.element_data = element_data
        self.fail_on_step = fail_on_step
    async def locate_and_interact(self, page, action, **kw):
        if self.fail_on_step == action:
            from app.services.smart_locator import ElementNotFoundError
            raise ElementNotFoundError("not found")
        return {"status": "success"}


class FakeElementService:
    def __init__(self, mapping):
        self.mapping = mapping
    async def find_by_name(self, project_id, element_name):
        return self.mapping.get(element_name)


class FakeSSE:
    def __init__(self): self.messages = []
    async def send_message(self, **kw): self.messages.append(kw)


class FakeDB:
    def __init__(self): self.added = []
    async def add(self, obj): self.added.append(obj)
    async def flush(self): pass
    async def commit(self): pass


def _make_script_asset(step_mapping):
    return ScriptAsset(
        id="s1", case_id="c1", project_id="p1", name="登录",
        content="def test_login(page): pass", version=1, status="confirmed",
        category="uncategorized", step_mapping=step_mapping, locator_source="element_library",
        last_status="never_run", run_count=0,
    )


def _make_exec_record():
    return ExecutionRecord(id="er1", exec_id="exec-1", project_id="p1",
                           exec_type="single", status="running", total_cases=1)


class TestScriptExecutorExecute:
    def _exec(self, script_asset, fail_on_step=None, mock_page=None, locator_factory=None):
        element_svc = FakeElementService({
            "用户名": {"element_id": "e1", "element_name": "用户名",
                      "locator_strategies": {"strategies": [{"type": "label", "value": "用户名", "score": 10}]},
                      "semantic_info": None}
        })
        import app.services.script_executor as exec_mod
        orig = getattr(exec_mod, "SmartLocator", None)
        # #5b T5: 允许调用方注入自定义 locator_factory (用于 heal_log/writeback 测试);
        # 默认仍用 #5a 的 FakeSmartLocator (返回 {"status":"success"} 无 heal_log).
        if locator_factory is not None:
            exec_mod.SmartLocator = locator_factory
        else:
            exec_mod.SmartLocator = lambda ed, gateway=None: FakeSmartLocator(ed, fail_on_step=fail_on_step)
        db = FakeDB()
        from unittest.mock import MagicMock, AsyncMock
        storage = MagicMock(); storage.upload_bytes = AsyncMock(return_value="/static/x.png")
        gw = MagicMock(); gw.tokens = 50
        svc = ScriptExecutor(db=db, gateway=gw, storage=storage, element_svc=element_svc)
        # monkeypatch _launch_browser 避免真实启动 Playwright; 返回 mock page (默认 None)
        svc._launch_browser = AsyncMock(return_value=mock_page)
        er = _make_exec_record()
        sse = FakeSSE()
        try:
            detail = asyncio_run(svc.execute(script_asset,
                                             config=MagicMock(headless=True, timeout=60, max_failures=8),
                                             target_url="http://x", sse=sse, execution_record=er))
        finally:
            if orig: exec_mod.SmartLocator = orig
        return detail, sse, db

    def test_all_steps_pass(self):
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        detail, sse, db = self._exec(sa)
        assert detail.status == "pass"
        assert sa.last_status == "passed"
        assert sa.run_count == 1
        assert sa.last_run_at is not None
        assert any("完成" in (m.get("content", "")) for m in sse.messages)

    def test_step_failure_records_detail(self):
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        detail, sse, db = self._exec(sa, fail_on_step="fill")
        assert detail.status == "fail"
        assert detail.error_type == "locate_failed"
        assert sa.last_status == "failed"

    def test_missing_element_name_step_skipped(self):
        # 旧 step_mapping 无 element_name
        sa = _make_script_asset([{"step": 1, "action": "fill", "status": "ok",
                                  "case_req": "", "impl": "x"}])
        detail, sse, db = self._exec(sa)
        assert detail.status == "fail"
        assert detail.error_type == "script_error"
        assert "element_name" in (detail.error_msg or "").lower() or "缺" in (detail.error_msg or "")

    def test_quick_run_no_execution_record(self):
        """quick-run: execution_record=None -> 不落 ExecutionDetail, 返回 None."""
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        element_svc = FakeElementService({
            "用户名": {"element_id": "e1", "element_name": "用户名",
                      "locator_strategies": {"strategies": [{"type": "label", "value": "用户名", "score": 10}]},
                      "semantic_info": None}
        })
        import app.services.script_executor as exec_mod
        orig = getattr(exec_mod, "SmartLocator", None)
        exec_mod.SmartLocator = lambda ed, gateway=None: FakeSmartLocator(ed)
        db = FakeDB()
        storage = MagicMock(); storage.upload_bytes = AsyncMock(return_value="/static/x.png")
        gw = MagicMock(); gw.tokens = 0
        svc = ScriptExecutor(db=db, gateway=gw, storage=storage, element_svc=element_svc)
        svc._launch_browser = AsyncMock(return_value=None)  # quick-run 不真实启动
        sse = FakeSSE()
        try:
            detail = asyncio_run(svc.execute(
                sa, config=MagicMock(headless=True, timeout=60, max_failures=8),
                target_url="http://x", sse=sse, execution_record=None,
            ))
        finally:
            if orig:
                exec_mod.SmartLocator = orig
        assert detail is None  # quick-run 不落 detail
        # SSE 完成消息仍发
        assert any("完成" in (m.get("content", "")) for m in sse.messages)

    def test_assertion_toast_message_pass(self):
        """断言 toast_message is_valid=True 且页面含 expected → 通过."""
        page = MagicMock()
        page.text_content = AsyncMock(return_value="操作成功，已保存")
        page.close = AsyncMock()
        sa = _make_script_asset([{"step": 1, "action": "click", "element_name": "用户名",
                                  "value": "", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None,
                                  "assertion": {"type": "toast_message", "expected": "成功", "is_valid": True}}])
        detail, sse, db = self._exec(sa, mock_page=page)
        assert detail.status == "pass"
        assert sa.last_status == "passed"

    def test_assertion_toast_message_fail_classified_assertion_failed(self):
        """断言 toast_message is_valid=True 但页面不含 expected → assertion_failed."""
        page = MagicMock()
        page.text_content = AsyncMock(return_value="出错了，请联系管理员")
        page.screenshot = AsyncMock(return_value=b"png")
        page.content = AsyncMock(return_value="<html>dom</html>")
        page.close = AsyncMock()
        sa = _make_script_asset([{"step": 1, "action": "click", "element_name": "用户名",
                                  "value": "", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None,
                                  "assertion": {"type": "toast_message", "expected": "成功", "is_valid": True}}])
        detail, sse, db = self._exec(sa, mock_page=page)
        assert detail.status == "fail"
        assert detail.error_type == "assertion_failed"
        assert sa.last_status == "failed"

    def test_assertion_not_valid_skipped(self):
        """is_valid=False 的断言不验证, 步骤通过."""
        page = MagicMock()
        page.close = AsyncMock()
        sa = _make_script_asset([{"step": 1, "action": "click", "element_name": "用户名",
                                  "value": "", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None,
                                  "assertion": {"type": "toast_message", "expected": "成功", "is_valid": False}}])
        detail, sse, db = self._exec(sa, mock_page=page)
        assert detail.status == "pass"

    def test_assertion_other_type_skipped(self):
        """status_changed 等暂未实现的断言类型跳过 (不抛错)."""
        page = MagicMock()
        page.close = AsyncMock()
        sa = _make_script_asset([{"step": 1, "action": "click", "element_name": "用户名",
                                  "value": "", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None,
                                  "assertion": {"type": "status_changed", "expected": "首页", "is_valid": True}}])
        detail, sse, db = self._exec(sa, mock_page=page)
        assert detail.status == "pass"

    def test_launches_browser_when_page_none(self):
        """page=None 时调用 _launch_browser (真实启动占位)."""
        page = MagicMock()
        page.close = AsyncMock()
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        detail, sse, db = self._exec(sa, mock_page=page)
        assert detail.status == "pass"


class TestScriptExecutorHealFill:
    """#5b T5: ScriptExecutor 捕获 heal_log/writeback → 填 ExecutionDetail + 调 _do_writeback."""

    def test_heal_success_fills_execution_detail(self):
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        # mock SmartLocator 返回带 heal_log + writeback
        import app.services.script_executor as exec_mod

        class FakeSL:
            def __init__(self, ed, gateway=None):
                pass

            async def locate_and_interact(self, page, action, **kw):
                return {"status": "success", "action": action,
                        "heal_log": [{"level": 2, "strategy": "dom_fuzz", "success": True}],
                        "writeback": {"element_id": "e1", "locator": {"type": "label", "value": "用户名"}}}

        # patch ElementService.writeback_healed_locator 防止真实 DB 调用
        import app.services.element_service as es_mod
        orig_es = es_mod.ElementService

        class FakeES:
            def __init__(self, db):
                self.db = db

            async def writeback_healed_locator(self, element_id, healed_locator):
                return True

        es_mod.ElementService = FakeES
        try:
            detail, sse, db = TestScriptExecutorExecute()._exec(sa, locator_factory=FakeSL)
            # 执行成功 + heal_status 应为 healed
            assert detail.status == "pass"
            assert detail.heal_status == "healed"
            assert detail.heal_log is not None
            assert len(detail.heal_log) == 1
        finally:
            es_mod.ElementService = orig_es

    def test_no_heal_sets_none_status(self):
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        import app.services.script_executor as exec_mod

        class FakeSL:
            def __init__(self, ed, gateway=None):
                pass

            async def locate_and_interact(self, page, action, **kw):
                return {"status": "success", "action": action}  # 无 heal_log

        try:
            detail, sse, db = TestScriptExecutorExecute()._exec(sa, locator_factory=FakeSL)
            assert detail.status == "pass"
            assert detail.heal_status == "none"
            assert detail.heal_log is None
        finally:
            pass

    def test_heal_success_sends_self_heal_sse_marker(self):
        """#5b T5: 有 heal_log 时 SSE 成功消息带"（自愈）"标记."""
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        import app.services.script_executor as exec_mod

        class FakeSL:
            def __init__(self, ed, gateway=None):
                pass

            async def locate_and_interact(self, page, action, **kw):
                return {"status": "success", "action": action,
                        "heal_log": [{"level": 2, "strategy": "dom_fuzz", "success": True}],
                        "writeback": None}

        try:
            detail, sse, db = TestScriptExecutorExecute()._exec(sa, locator_factory=FakeSL)
            assert detail.status == "pass"
            # SSE 应有带"（自愈）"的成功消息
            assert any("自愈" in (m.get("content", "")) for m in sse.messages)
        finally:
            pass

    def test_heal_failure_keeps_heal_log_and_sets_failed_status(self):
        """审查 #3: 自愈全失败 (抛异常) 时 heal_log 保留, heal_status="failed"."""
        sa = _make_script_asset([{"step": 1, "action": "click", "element_name": "用户名",
                                  "value": "", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])

        class FakeSL:
            def __init__(self, ed, gateway=None):
                pass

            async def locate_and_interact(self, page, action, **kw):
                from app.services.smart_locator import ElementNotFoundError
                # 模拟 SelfHealEngine 全失败: 异常携带失败 heal_log
                raise ElementNotFoundError("self-heal failed", heal_log=[
                    {"level": 1, "strategy": "semantic", "success": False},
                    {"level": 2, "strategy": "dom_fuzz", "success": False},
                    {"level": 3, "strategy": "ai_dom", "success": False},
                    {"level": 4, "strategy": "visual", "success": False},
                ])

        detail, sse, db = TestScriptExecutorExecute()._exec(sa, locator_factory=FakeSL)
        assert detail.status == "fail"
        assert detail.error_type == "locate_failed"
        # heal_log 不丢失 + heal_status="failed"
        assert detail.heal_log is not None
        assert len(detail.heal_log) == 4
        assert all(h.get("success") is False for h in detail.heal_log)
        assert detail.heal_status == "failed"

    def test_writeback_invokes_element_service(self):
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        import app.services.script_executor as exec_mod

        wb_calls = []

        class FakeSL:
            def __init__(self, ed, gateway=None):
                pass

            async def locate_and_interact(self, page, action, **kw):
                return {"status": "success", "action": action,
                        "heal_log": [{"level": 2, "strategy": "dom_fuzz", "success": True}],
                        "writeback": {"element_id": "e1", "locator": {"type": "label", "value": "用户名"}}}

        # patch ElementService.writeback_healed_locator (在 script_executor 顶层 import)
        import app.services.element_service as es_mod
        orig_es = es_mod.ElementService

        class FakeES:
            def __init__(self, db):
                self.db = db

            async def writeback_healed_locator(self, element_id, healed_locator):
                wb_calls.append((element_id, healed_locator))
                return True

        es_mod.ElementService = FakeES
        try:
            detail, sse, db = TestScriptExecutorExecute()._exec(sa, locator_factory=FakeSL)
            assert detail.status == "pass"
            assert len(wb_calls) == 1
            assert wb_calls[0][0] == "e1"
        finally:
            es_mod.ElementService = orig_es

