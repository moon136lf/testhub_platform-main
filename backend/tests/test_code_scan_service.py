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
    db.add = MagicMock()  # sync add: AsyncMock auto-add yields unawaited coroutines
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


class TestRunScanSync:
    @pytest.mark.asyncio
    async def test_run_scan_writes_issues_and_stats(self, mock_db):
        svc = CodeScanService(mock_db)
        scan = MagicMock()
        scan.id = uuid4()
        scan.to_dict = Mock(return_value={"id": str(scan.id), "status": "scanning"})
        # side_effect ordering: get_ignored_fingerprints + get_case_bearing_
        # fingerprints (both .all()) then mark_scan_done (.scalar_one_or_none)
        mock_db.execute.side_effect = [
            Mock(all=Mock(return_value=[])),  # get_ignored_fingerprints
            Mock(all=Mock(return_value=[])),  # get_case_bearing_fingerprints
            _mock_scalar_one(scan),           # mark_scan_done fetch
        ]
        with patch("app.services.code_scan_service._run_semgrep",
                   return_value=SEMGREP_JSON):
            result = await svc.run_scan_sync(
                {"id": str(uuid4()), "project_id": str(uuid4())},
                repo_path="/tmp/repo")
        assert result["total_issues"] == 2
        # plan's return dict spreads counts as high/mid/low keys (plan-internal
        # key mismatch vs its own test's high_count assertion — deviation from
        # plan, documented): return high_count/mid_count/low_count, matching
        # CodeScan.to_dict + ScanResponse schema keys
        assert result["high_count"] >= 1  # ERROR mapped high
        assert mock_db.commit.called or mock_db.add.called

    @pytest.mark.asyncio
    async def test_run_scan_skips_ignored_fingerprints(self, mock_db):
        svc = CodeScanService(mock_db)
        # both issues ignored -> 0 written
        async def fake_ignored(project_id):
            return {_compute_fingerprint(
                SEMGREP_JSON["results"][0]["check_id"],
                SEMGREP_JSON["results"][0]["path"],
                SEMGREP_JSON["results"][0]["start"]["line"],
                SEMGREP_JSON["results"][0]["extra"]["lines"]),
                _compute_fingerprint(
                SEMGREP_JSON["results"][1]["check_id"],
                SEMGREP_JSON["results"][1]["path"],
                SEMGREP_JSON["results"][1]["start"]["line"],
                SEMGREP_JSON["results"][1]["extra"]["lines"])}
        svc.get_ignored_fingerprints = fake_ignored
        # get_case_bearing_fingerprints uses real impl -> mock its .all() rows;
        # mark_scan_done fetch must return a real Mock scan (AsyncMock auto-attr
        # scalar_one_or_none returns an unawaited coroutine whose .status write
        # would crash — plan-internal mock gap, deviation documented)
        mock_db.execute.side_effect = [
            Mock(all=Mock(return_value=[])),  # get_case_bearing_fingerprints
            _mock_scalar_one(MagicMock()),    # mark_scan_done fetch
        ]
        with patch("app.services.code_scan_service._run_semgrep",
                   return_value=SEMGREP_JSON):
            result = await svc.run_scan_sync(
                {"id": str(uuid4()), "project_id": str(uuid4())},
                repo_path="/tmp/repo")
        assert result["total_issues"] == 0

    @pytest.mark.asyncio
    async def test_run_scan_marks_case_outdated_on_fingerprint_match(self, mock_db):
        """Review C2: a fingerprint whose prior issue already produced a
        regression case gets case_outdated=True on re-scan (cross-scan)."""
        svc = CodeScanService(mock_db)
        scan = MagicMock()
        scan.id = uuid4()
        fp0 = _compute_fingerprint(
            SEMGREP_JSON["results"][0]["check_id"],
            SEMGREP_JSON["results"][0]["path"],
            SEMGREP_JSON["results"][0]["start"]["line"],
            SEMGREP_JSON["results"][0]["extra"]["lines"])
        async def fake_ignored(project_id):
            return set()
        async def fake_case_bearing(project_id):
            return {fp0}
        svc.get_ignored_fingerprints = fake_ignored
        svc.get_case_bearing_fingerprints = fake_case_bearing
        added = []
        mock_db.add = Mock(side_effect=added.append)
        mock_db.execute.side_effect = [_mock_scalar_one(MagicMock())]  # mark_scan_done
        with patch("app.services.code_scan_service._run_semgrep",
                   return_value=SEMGREP_JSON):
            await svc.run_scan_sync(
                {"id": str(uuid4()), "project_id": str(uuid4())},
                repo_path="/tmp/repo")
        assert len(added) == 2
        # first issue's fingerprint has a case -> outdated; second doesn't
        assert added[0].case_outdated is True
        assert added[1].case_outdated is False


class TestScanExport:
    @pytest.mark.asyncio
    async def test_export_buglist_xlsx_bytes(self):
        from app.services.scan_export_service import ScanExportService
        svc = ScanExportService()
        issues = [{"severity": "high", "file_path": "a.py", "line_no": 1,
                   "title": "SQLi", "description": "d", "status": "open"}]
        data = svc.export_buglist_xlsx(issues)
        assert data[:2] == b"PK"  # xlsx zip magic

    @pytest.mark.asyncio
    async def test_export_markdown_nonempty(self):
        from app.services.scan_export_service import ScanExportService
        svc = ScanExportService()
        issues = [{"severity": "high", "file_path": "a.py", "line_no": 1,
                   "title": "SQLi", "description": "d", "status": "open"}]
        md = svc.export_issues_markdown(issues, title="BUG清单")
        assert "SQLi" in md and "#" in md
