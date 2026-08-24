# backend/tests/test_script_tasks.py
"""Celery task test (direct call, not via broker)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.tasks.script_tasks import convert_scripts_task_impl


class FakeSSE:
    async def send_message(self, **kw):
        pass


def test_task_runs_all_cases_and_writes_assets(monkeypatch):
    from app.tasks import script_tasks
    monkeypatch.setattr(script_tasks, "SSEStream", lambda sid: FakeSSE())

    cases = [
        {"id": "c1", "name": "登录", "project_id": "p1",
         "steps": [{"step": 1, "action": "输入用户名admin", "expected": "ok"}],
         "expected_result": "进入首页"},
    ]
    gateway = MagicMock()
    gateway.chat = AsyncMock(side_effect=[
        {"content": '[{"step":1,"action":"fill","target":"用户名","value":"admin"}]', "tokens": 50},
        {"content": '[{"step":1,"assertion_type":"status_changed","target":"p","expected":"首页","is_valid":true}]', "tokens": 50},
        {"content": 'def t(page):\n    page.get_by_label("用户名").fill("admin")\n', "tokens": 50},
    ])
    gateway.tokens = 150

    lookup = MagicMock()
    lookup.find = AsyncMock(return_value='page.get_by_label("用户名")')

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    # session lookup returns the case itself
    db.execute = AsyncMock()
    db.scalar_one_or_none = MagicMock(return_value=None)

    session_id = "s1"
    result = asyncio.run(convert_scripts_task_impl(session_id, cases, gateway=gateway, lookup=lookup, db=db))
    assert result["status"] == "done"
    assert result["tokens_used"] == 150
    assert result["generated_count"] == 1


def test_bad_llm_case_does_not_abort_batch(monkeypatch):
    from app.tasks import script_tasks

    class _FakeSSE:
        async def send_message(self, **kw):
            pass
    monkeypatch.setattr(script_tasks, "SSEStream", lambda sid: _FakeSSE())

    cases = [{"id": "c1", "name": "x", "project_id": "p1",
              "steps": [{"step": 1, "action": "a", "expected": "e"}],
              "expected_result": "r"}]
    gateway = MagicMock()
    # step1 returns invalid JSON -> json.loads raises JSONDecodeError (a ValueError)
    gateway.chat = AsyncMock(return_value={"content": "not valid json", "tokens": 5})
    gateway.tokens = 5
    lookup = MagicMock()
    lookup.find = AsyncMock(return_value=None)
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    db.scalar_one_or_none = MagicMock(return_value=None)

    result = asyncio.run(script_tasks.convert_scripts_task_impl(
        "s1", cases, gateway=gateway, lookup=lookup, db=db))
    assert result["status"] == "done"
    assert result["generated_count"] == 0
    assert result["tokens_used"] == 5
