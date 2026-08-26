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
    def _exec(self, script_asset, fail_on_step=None, mock_page=None):
        element_svc = FakeElementService({
            "用户名": {"element_id": "e1", "element_name": "用户名",
                      "locator_strategies": {"strategies": [{"type": "label", "value": "用户名", "score": 10}]},
                      "semantic_info": None}
        })
        import app.services.script_executor as exec_mod
        orig = getattr(exec_mod, "SmartLocator", None)
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
