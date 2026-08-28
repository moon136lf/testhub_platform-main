"""AIFixService tests (mock AIGateway)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

from app.services.ai_fix_service import AIFixService


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def mock_gateway():
    gw = MagicMock()
    gw.chat = AsyncMock(return_value={
        "content": '{"suggestion": "use parameterized query", '
                   '"fixed_code": "cursor.execute(sql, (uid,))", '
                   '"original_code": "cursor.execute(f\'...{uid}...\')"}',
        "tokens": 120,
    })
    return gw


@pytest.fixture
def issue_row():
    # plan used MagicMock for the issue row, but MagicMock auto-attrs break two
    # plan assertions: (a) issue.to_dict() returns a MagicMock not a dict, so
    # result["ai_suggestion"] is unsatisfiable; (b) attribute writes via
    # property need a setter. A spec'd Mock backed by a plain dict behaves like
    # the ORM row: attribute read/write reflected in to_dict (deviation from
    # plan, documented; same spirit as test_code_scan_service.py T2 to_dict fix).
    state = {
        "id": str(uuid4()),
        "title": "SQL injection risk",
        "description": "f-string in execute",
        "file_path": "src/db.py",
        "line_no": 10,
        "example_code": "cursor.execute(f'SELECT * FROM u WHERE id={uid}')",
        "severity": "high",
        "ai_suggestion": None,
    }

    class _IssueRow:
        def __getattr__(self, name):
            try:
                return state[name]
            except KeyError:
                raise AttributeError(name)

        def __setattr__(self, name, value):
            state[name] = value

        def to_dict(self):
            # mirrors CodeIssue.to_dict() key set
            return {
                "id": state["id"], "scan_id": None, "severity": state["severity"],
                "file_path": state["file_path"], "line_no": state["line_no"],
                "title": state["title"], "description": state["description"],
                "ai_suggestion": state["ai_suggestion"],
                "example_code": state["example_code"], "status": "open",
                "source_commit": None, "fingerprint": None,
                "case_outdated": False, "handled_by": None, "handled_at": None,
            }

    return _IssueRow()


class TestAIFix:
    @pytest.mark.asyncio
    async def test_generate_fix_writes_jsonb(self, mock_db, mock_gateway, issue_row):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=issue_row))
        svc = AIFixService(mock_db, mock_gateway)
        result = await svc.generate_fix(str(issue_row.id), project_id=str(uuid4()))
        # JSONB write must be the parsed dict (issue.ai_suggestion mutated)
        assert issue_row.ai_suggestion["suggestion"] == "use parameterized query"
        assert issue_row.ai_suggestion["fixed_code"].startswith("cursor.execute(sql")
        # to_dict live-view: after mutation it reflects the suggestion
        assert result["ai_suggestion"]["suggestion"] == "use parameterized query"
        assert mock_db.commit.called
        # gateway called with project token tracking
        assert mock_gateway.chat.called

    @pytest.mark.asyncio
    async def test_generate_fix_bad_json_degrades(self, mock_db, issue_row):
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "not json at all", "tokens": 50})
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=issue_row))
        svc = AIFixService(mock_db, gw)
        result = await svc.generate_fix(str(issue_row.id), project_id=str(uuid4()))
        # degraded: raw content wrapped, no crash
        assert issue_row.ai_suggestion["suggestion"].startswith("not json")
        assert result["ai_suggestion"]["suggestion"].startswith("not json")

    @pytest.mark.asyncio
    async def test_generate_fix_missing_issue(self, mock_db, mock_gateway):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = AIFixService(mock_db, mock_gateway)
        assert await svc.generate_fix(str(uuid4()), project_id=str(uuid4())) is None
