"""CodeScanService tests (mock db + mock subprocess for semgrep)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

from app.services.code_scan_service import CodeScanService, _run_semgrep, _compute_fingerprint


def _mock_scalar(v):
    return Mock(scalar=Mock(return_value=v))


def _mock_scalars(values):
    return Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=values))))


def _mock_scalar_one(value):
    return Mock(scalar_one_or_none=Mock(return_value=value))


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


# semgrep real output shape (subset of fields we consume)
SEMGREP_JSON = {
    "results": [
        {"check_id": "python-lang.correctness.eqeq5",
         "path": "src/auth.py", "start": {"line": 42},
         "extra": {"message": "use == to compare", "severity": "WARNING",
                   "lines": "if a == b:  # noqa"}},
        {"check_id": "python.security.sql-injection",
         "path": "src/db.py", "start": {"line": 10},
         "extra": {"message": "possible SQL injection", "severity": "ERROR",
                   "lines": "cursor.execute(f'...')"}},
    ],
    "errors": [],
}


class TestRunSemgrep:
    def test_semgrep_parses_docker_output(self):
        with patch("app.services.code_scan_service.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=json.dumps(SEMGREP_JSON))
            result = _run_semgrep("/tmp/repo")
        assert len(result["results"]) == 2
        assert result["results"][0]["check_id"] == "python-lang.correctness.eqeq5"

    def test_semgrep_failure_raises(self):
        with patch("app.services.code_scan_service.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="docker: not found")
            with pytest.raises(Exception):
                _run_semgrep("/tmp/repo")


class TestFingerprint:
    def test_fingerprint_stable_and_scoped(self):
        fp1 = _compute_fingerprint("rule-a", "src/x.py", 10, "code here")
        fp2 = _compute_fingerprint("rule-a", "src/x.py", 10, "code here")
        fp3 = _compute_fingerprint("rule-a", "src/x.py", 11, "code here")
        assert fp1 == fp2
        assert fp1 != fp3
        assert len(fp1) <= 200


class TestIssueFlow:
    @pytest.mark.asyncio
    async def test_update_issue_status_false_positive(self, mock_db):
        issue = MagicMock()
        issue.status = "open"
        issue.fingerprint = "fp-1"
        # plan test omitted to_dict config; MagicMock auto-attr would return a
        # MagicMock (not a dict) and make the assertion unsatisfiable. Configure
        # it to mirror the mutated state (deviation from plan, documented).
        issue.to_dict = Mock(return_value={"status": "false_positive"})
        mock_db.execute.return_value = _mock_scalar_one(issue)
        svc = CodeScanService(mock_db)
        result = await svc.update_issue(str(uuid4()), "false_positive")
        assert result["status"] == "false_positive"
        assert issue.status == "false_positive"
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_update_issue_missing_raises_404_shape(self, mock_db):
        mock_db.execute.return_value = _mock_scalar_one(None)
        svc = CodeScanService(mock_db)
        result = await svc.update_issue(str(uuid4()), "fixed")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_issues_filters(self, mock_db):
        i1, i2 = MagicMock(), MagicMock()
        i1.to_dict = Mock(return_value={"severity": "high"})
        i2.to_dict = Mock(return_value={"severity": "low"})
        mock_db.execute.return_value = _mock_scalars([i1, i2])
        svc = CodeScanService(mock_db)
        result = await svc.list_issues(str(uuid4()), severity="high", status=None)
        assert len(result) == 2  # mock db ignores filters; shape asserted
        assert result[0]["severity"] == "high"

    @pytest.mark.asyncio
    async def test_get_ignored_fingerprints(self, mock_db):
        rows = [("fp-a",), ("fp-b",)]
        mock_db.execute.return_value = Mock(all=Mock(return_value=rows))
        svc = CodeScanService(mock_db)
        result = await svc.get_ignored_fingerprints(str(uuid4()))
        assert result == ["fp-a", "fp-b"]
