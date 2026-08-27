"""Dashboard API endpoint tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _fake_overview():
    return {
        "stats": {"element_count": 1, "case_count": 2, "automated_count": 3, "point_count": 4},
        "today": {"ai_calls": 5, "tokens_used": 6},
        "element_distribution": [{"type": "button", "count": 1}],
        "case_distribution": [{"type": "functional", "count": 2}],
        "ai_trend": [{"date": "2026-08-27", "call_count": 1, "tokens": 100}],
    }


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


class TestOverview:
    def test_overview_returns_all_sections(self, client):
        svc = MagicMock()
        svc.get_overview = AsyncMock(return_value=_fake_overview())
        from app.api.v1.dashboard import get_dashboard_service
        app.dependency_overrides[get_dashboard_service] = lambda: svc
        r = client.get("/api/v1/dashboard/overview")
        assert r.status_code == 200
        data = r.json()
        assert data["stats"]["element_count"] == 1
        assert data["today"]["ai_calls"] == 5
        assert data["element_distribution"][0]["type"] == "button"
        assert data["ai_trend"][0]["tokens"] == 100

    def test_overview_passes_query_params(self, client):
        svc = MagicMock()
        svc.get_overview = AsyncMock(return_value=_fake_overview())
        from app.api.v1.dashboard import get_dashboard_service
        app.dependency_overrides[get_dashboard_service] = lambda: svc
        r = client.get("/api/v1/dashboard/overview",
                       params={"project_id": "00000000-0000-0000-0000-000000000001", "days": 30})
        assert r.status_code == 200
        svc.get_overview.assert_called_once_with("00000000-0000-0000-0000-000000000001", days=30)

    def test_overview_days_out_of_range_422(self, client):
        r = client.get("/api/v1/dashboard/overview", params={"days": 999})
        assert r.status_code == 422
