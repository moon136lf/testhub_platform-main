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
