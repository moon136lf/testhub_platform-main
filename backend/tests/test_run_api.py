"""run/batch-run/quick-run endpoint tests (mock db + patch task.delay)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.api.v1.scripts import run_script, batch_run_scripts, quick_run_script


def asyncio_run(coro): return asyncio.run(coro)


def _mock_db_with_script():
    db = MagicMock()
    script = MagicMock()
    script.id = "00000000-0000-0000-0000-000000000002"
    script.project_id = "00000000-0000-0000-0000-000000000001"
    script.name = "登录"
    script.content = "def t(page): pass"
    script.step_mapping = []
    script.status = "confirmed"
    result = MagicMock()
    result.scalar_one_or_none.return_value = script
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db, script


class TestRunEndpoint:
    def test_run_returns_session_id(self, monkeypatch):
        from app.api.v1 import scripts as scripts_api
        fake_task = type("T", (), {"id": "task-1"})()
        monkeypatch.setattr(scripts_api, "run_scripts_task",
                            type("M", (), {"delay": staticmethod(lambda **kw: fake_task)}))
        db, script = _mock_db_with_script()
        req = MagicMock()
        req.script_id = "00000000-0000-0000-0000-000000000002"
        req.config.model_dump.return_value = {"headless": True, "timeout": 60, "max_failures": 8}
        resp = asyncio_run(run_script(request=req, db=db))
        assert resp["code"] == 0
        assert "session_id" in resp["data"]
        assert resp["data"]["sse_url"].startswith("/api/sse/stream/")

    def test_run_script_not_found(self):
        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        with pytest.raises(Exception):
            req = MagicMock()
            req.script_id = "00000000-0000-0000-0000-000000000002"
            req.config.model_dump.return_value = {"headless": True, "timeout": 60, "max_failures": 8}
            asyncio_run(run_script(request=req, db=db))


class TestQuickRunEndpoint:
    def test_quick_run_returns_session_id(self, monkeypatch):
        from app.api.v1 import scripts as scripts_api
        fake_task = type("T", (), {"id": "task-q"})()
        monkeypatch.setattr(scripts_api, "run_scripts_task",
                            type("M", (), {"delay": staticmethod(lambda **kw: fake_task)}))
        db = MagicMock()
        req = MagicMock()
        req.script_content = "def t(page): pass"
        req.target_url = "http://x"
        req.headless = True
        resp = asyncio_run(quick_run_script(request=req, db=db))
        assert resp["code"] == 0
        assert "session_id" in resp["data"]


class TestBatchRunEndpoint:
    def test_batch_run_returns_session_id(self, monkeypatch):
        from app.api.v1 import scripts as scripts_api
        fake_task = type("T", (), {"id": "task-b"})()
        monkeypatch.setattr(scripts_api, "run_scripts_task",
                            type("M", (), {"delay": staticmethod(lambda **kw: fake_task)}))
        db = MagicMock()
        req = MagicMock()
        req.script_ids = ["00000000-0000-0000-0000-000000000002"]
        req.config.model_dump.return_value = {"headless": True, "timeout": 60, "max_failures": 8}
        resp = asyncio_run(batch_run_scripts(request=req, db=db))
        assert resp["code"] == 0
        assert "session_id" in resp["data"]
