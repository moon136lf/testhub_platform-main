"""Whitescan API endpoint tests (dependency overrides)."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app

PID = "00000000-0000-0000-0000-000000000001"
SCAN = "22222222-2222-2222-2222-222222222222"
ISSUE = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


def _override(mock_svc):
    from app.api.v1.whitescan import get_scan_service
    app.dependency_overrides[get_scan_service] = lambda: mock_svc


class TestScanEndpoints:
    def test_trigger_scan(self, client):
        svc = MagicMock()
        svc.create_scan = AsyncMock(return_value={"id": SCAN, "status": "scanning"})
        _override(svc)
        # Plan's test didn't stub run_scan_task.delay -> real Celery tries Redis,
        # retries 20x (~40s) then 503 (deviation from plan, documented).
        with patch("app.tasks.code_scan_tasks.run_scan_task") as mock_task:
            mock_task.delay = MagicMock()
            r = client.post("/api/v1/whitescan/scan",
                            json={"project_id": PID, "repo_url": "https://git.example/x.git"})
        assert r.status_code == 200
        assert r.json()["data"]["scan_id"] == SCAN
        svc.create_scan.assert_awaited_once()

    def test_list_scans(self, client):
        svc = MagicMock()
        svc.list_scans = AsyncMock(return_value={"total": 1, "page": 1, "page_size": 20,
                                                  "items": [{"id": SCAN, "status": "done"}]})
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans?project_id={PID}")
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 1

    def test_get_scan(self, client):
        svc = MagicMock()
        svc.get_scan = AsyncMock(return_value={"id": SCAN, "status": "done", "total_issues": 2})
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans/{SCAN}")
        assert r.status_code == 200
        assert r.json()["data"]["total_issues"] == 2

    def test_list_issues(self, client):
        svc = MagicMock()
        svc.list_issues = AsyncMock(return_value=[{"id": ISSUE, "severity": "high"}])
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans/{SCAN}/issues?severity=high")
        assert r.status_code == 200
        assert r.json()["data"][0]["severity"] == "high"


class TestIssueEndpoints:
    def test_update_issue(self, client):
        svc = MagicMock()
        svc.update_issue = AsyncMock(return_value={"id": ISSUE, "status": "fixed"})
        _override(svc)
        r = client.patch(f"/api/v1/whitescan/issues/{ISSUE}", json={"status": "fixed"})
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "fixed"

    def test_ai_fix(self, client):
        # Plan's test only mocked svc.ai_fix/get_issue, but the endpoint builds a
        # real AIFixService over the real db dependency -> real query on
        # code_issue returns no row for a random UUID -> 404 (plan-internal
        # mismatch, deviation documented). Mock the AIFixService.generate_fix
        # path instead: patch AIGateway + let the real service hit the table?
        # No - keep it hermetic: patch AIFixService.generate_fix.
        with patch("app.services.ai_fix_service.AIFixService.generate_fix",
                   new=AsyncMock(return_value={"id": ISSUE,
                                               "ai_suggestion": {"suggestion": "s",
                                                                 "fixed_code": "f"}})):
            r = client.post(f"/api/v1/whitescan/issues/{ISSUE}/ai-fix", params={"project_id": PID})
        assert r.status_code == 200
        assert r.json()["data"]["ai_suggestion"]["suggestion"] == "s"


class TestGenerateAndExport:
    def test_generate_cases(self, client):
        svc = MagicMock()
        # Plan's test only set svc.generate_cases, but the endpoint first calls
        # svc.list_issues(scan_id) -> MagicMock auto-attr is not awaitable
        # (plan-internal mismatch, deviation documented). Stub list_issues too;
        # the endpoint's inlined generate/persist flow is service-level logic
        # covered by test_regression_case_generator — here we mock the whole
        # batch path via patching RegressionCaseGenerator.batch_generate.
        svc.list_issues = AsyncMock(return_value=[])
        _override(svc)
        with patch("app.api.v1.whitescan.RegressionCaseGenerator") as mock_gen_cls:
            mock_gen_cls.return_value.batch_generate = AsyncMock(
                return_value={"generated_count": 2, "skipped_count": 1,
                              "failed_count": 0, "errors": []})
            r = client.post(f"/api/v1/whitescan/scans/{SCAN}/generate-cases",
                            params={"project_id": PID})
        assert r.status_code == 200
        assert r.json()["data"]["generated_count"] == 2

    def test_export_xlsx(self, client):
        svc = MagicMock()
        # Plan's test set svc.export_scan, but the endpoint calls
        # svc.list_issues + ScanExportService.export_buglist_xlsx (plan-internal
        # mismatch, deviation documented): stub list_issues with a real issue and
        # assert the real xlsx bytes carry the PK magic.
        svc.list_issues = AsyncMock(return_value=[{
            "id": ISSUE, "scan_id": SCAN, "severity": "high", "file_path": "a.py",
            "line_no": 1, "title": "SQLi", "description": "d", "status": "open",
        }])
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans/{SCAN}/export?format=xlsx")
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
