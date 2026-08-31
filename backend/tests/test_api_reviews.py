"""Reviews API endpoint tests."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app

PID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


def _override(mock_svc):
    from app.api.v1.reviews import get_review_service
    app.dependency_overrides[get_review_service] = lambda: mock_svc


class TestStats:
    def test_stats(self, client):
        svc = MagicMock()
        svc.get_review_stats = AsyncMock(return_value={
            "review_status": {"pending": 3}, "feasibility": {"full": 2},
            "automation_rate": 66.7, "total_cases": 3})
        _override(svc)
        r = client.get(f"/api/v1/reviews/stats?project_id={PID}")
        assert r.status_code == 200
        assert r.json()["automation_rate"] == 66.7


class TestBatchRefine:
    def test_batch_refine(self, client):
        svc = MagicMock()
        svc.batch_refine = AsyncMock(return_value=[
            {"case_id": "c1", "score": 90, "feasibility_level": "full", "suggestion_count": 2}])
        _override(svc)
        r = client.post("/api/v1/reviews/batch-refine",
                        json={"project_id": PID, "case_ids": ["c1"]})
        assert r.status_code == 200
        assert r.json()[0]["score"] == 90

    def test_batch_refine_empty_ids_422(self, client):
        r = client.post("/api/v1/reviews/batch-refine",
                        json={"project_id": PID, "case_ids": []})
        assert r.status_code == 422


class TestReport:
    def test_report(self, client):
        svc = MagicMock()
        svc.get_project_refinement_report = AsyncMock(return_value={
            "case_count": 1, "refined_at": "2026-08-25T10:00:00",
            "suggestions": [{"case_id": "c1", "case_name": "登录", "id": "s1",
                             "dimension": "断言增强", "status": "pending"}]})
        _override(svc)
        r = client.get(f"/api/v1/reviews/refinement-report?project_id={PID}")
        assert r.status_code == 200
        assert r.json()["suggestions"][0]["case_name"] == "登录"


class TestBatchReview:
    def test_batch_review(self, client):
        svc = MagicMock()
        svc.batch_update_review = AsyncMock(return_value={"success_count": 2, "failure_count": 0})
        _override(svc)
        r = client.post("/api/v1/reviews/batch-review",
                        json={"project_id": PID, "case_ids": ["c1", "c2"],
                              "review_status": "passed", "review_comment": "ok"})
        assert r.status_code == 200
        assert r.json()["success_count"] == 2

    def test_batch_review_invalid_status_422(self, client):
        r = client.post("/api/v1/reviews/batch-review",
                        json={"project_id": PID, "case_ids": ["c1"],
                              "review_status": "bogus"})
        assert r.status_code == 422
