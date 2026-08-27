"""Reports API endpoint tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _override(mock_svc):
    from app.api.v1.reports import get_query_service, get_generator_service
    app.dependency_overrides[get_query_service] = lambda: mock_svc
    app.dependency_overrides[get_generator_service] = lambda: mock_svc


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


class TestRecords:
    def test_list_records(self, client):
        svc = MagicMock()
        svc.list_records = AsyncMock(return_value={"total": 1, "page": 1, "page_size": 20,
                                                   "items": [{"id": "1", "exec_id": "E1"}]})
        _override(svc)
        r = client.get("/api/v1/reports/records?project_id=00000000-0000-0000-0000-000000000001")
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 1

    def test_get_detail(self, client):
        svc = MagicMock()
        svc.get_detail = AsyncMock(return_value={"record": {"exec_id": "E1"}, "fail_step_count": 2,
                                                 "details": []})
        _override(svc)
        r = client.get("/api/v1/reports/records/E1")
        assert r.status_code == 200
        assert r.json()["data"]["fail_step_count"] == 2

    def test_get_detail_missing(self, client):
        svc = MagicMock()
        svc.get_detail = AsyncMock(return_value=None)
        _override(svc)
        r = client.get("/api/v1/reports/records/no-such")
        assert r.status_code == 404


class TestTrend:
    def test_trend(self, client):
        svc = MagicMock()
        svc.get_trend = AsyncMock(return_value=[{"date": "2026-08-26", "pass_rate": 90.0, "exec_count": 3}])
        _override(svc)
        r = client.get("/api/v1/reports/trend?project_id=00000000-0000-0000-0000-000000000001&days=7")
        assert r.status_code == 200
        assert r.json()["data"][0]["pass_rate"] == 90.0


class TestGenerate:
    def test_generate(self, client):
        gen = MagicMock()
        gen.generate_report = AsyncMock(return_value={"html_url": "reports/E1.html", "pdf_url": "reports/E1.pdf", "regenerated": True})
        _override(gen)
        r = client.post("/api/v1/reports/E1/generate")
        assert r.status_code == 200
        assert r.json()["data"]["regenerated"] is True


class TestExport:
    def test_export_html(self, client):
        from app.api.v1 import reports as reports_api
        reports_api.storage_client.get_object_bytes = MagicMock(return_value=b"<html>x</html>")
        svc = MagicMock()
        svc.get_detail = AsyncMock(return_value={"record": {"report_url": "reports/E1.html"}, "details": []})
        _override(svc)
        r = client.get("/api/v1/reports/E1/export?format=html")
        assert r.status_code == 200
        assert b"<html>" in r.content

    def test_export_404_when_not_generated(self, client):
        from app.api.v1 import reports as reports_api
        reports_api.storage_client.get_object_bytes = MagicMock(side_effect=Exception("NoSuchKey"))
        svc = MagicMock()
        svc.get_detail = AsyncMock(return_value={"record": {"exec_id": "E1"}, "details": []})
        _override(svc)
        r = client.get("/api/v1/reports/E1/export?format=pdf")
        assert r.status_code == 404
