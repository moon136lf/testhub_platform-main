"""Script execution schema tests."""
import pytest
from pydantic import ValidationError
from app.schemas.script import (
    SCRIPT_LAST_STATUSES, SCRIPT_CATEGORIES,
    RunConfig, RunRequest, BatchRunRequest, QuickRunRequest,
)


class TestEnums:
    def test_last_statuses(self):
        assert SCRIPT_LAST_STATUSES == ("never_run", "passed", "failed", "affected")

    def test_categories(self):
        assert SCRIPT_CATEGORIES == ("uncategorized", "ui_smoke", "full_regression", "core_flow", "interface_auto")


class TestRunSchemas:
    def _config(self):
        return dict(headless=True, timeout=60, max_failures=8)

    def test_run_request_minimal(self):
        r = RunRequest(script_id="00000000-0000-0000-0000-000000000001", config=self._config())
        assert r.config.headless is True
        assert r.config.timeout == 60
        assert r.config.max_failures == 8

    def test_run_request_invalid_script_id(self):
        with pytest.raises(ValidationError):
            RunRequest(script_id="not-a-uuid", config=self._config())

    def test_run_config_max_failures_range(self):
        with pytest.raises(ValidationError):
            RunConfig(headless=True, timeout=60, max_failures=0)
        with pytest.raises(ValidationError):
            RunConfig(headless=True, timeout=60, max_failures=101)

    def test_run_config_timeout_range(self):
        with pytest.raises(ValidationError):
            RunConfig(headless=True, timeout=4, max_failures=8)
        with pytest.raises(ValidationError):
            RunConfig(headless=True, timeout=601, max_failures=8)

    def test_batch_run_request_min_length(self):
        with pytest.raises(ValidationError):
            BatchRunRequest(script_ids=[], config=self._config())

    def test_quick_run_request(self):
        r = QuickRunRequest(script_content="def test_x(page): pass", target_url="http://x", headless=True)
        assert r.target_url == "http://x"

    def test_quick_run_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            QuickRunRequest(script_content="", target_url="http://x", headless=True)
