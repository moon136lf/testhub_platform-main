"""System API endpoint tests (FastAPI TestClient + dependency override)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1 import system as system_api


@pytest.fixture
def client():
    return TestClient(app)


def _override_service(mock_svc):
    """Override get_*_service deps to return mock_svc."""
    from app.api.v1.system import (
        get_setting_service, get_env_service,
        get_token_service, get_oplog_service,
    )
    app.dependency_overrides[get_setting_service] = lambda: mock_svc
    app.dependency_overrides[get_env_service] = lambda: mock_svc
    app.dependency_overrides[get_token_service] = lambda: mock_svc
    app.dependency_overrides[get_oplog_service] = lambda: mock_svc


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


class TestSettingsEndpoints:
    def test_list_settings(self, client):
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[{"id": "1", "category": "runtime",
                                            "key": "heal.strategy", "value": "SMART",
                                            "value_type": "string", "is_secret": False}])
        _override_service(svc)
        r = client.get("/api/v1/system/settings?category=runtime")
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        assert data["data"][0]["key"] == "heal.strategy"

    def test_update_setting(self, client):
        svc = MagicMock()
        svc.set = AsyncMock(return_value=None)
        _override_service(svc)
        r = client.put("/api/v1/system/settings/heal.strategy?category=runtime",
                       json={"value": "SMART", "value_type": "string", "is_secret": False})
        assert r.status_code == 200
        svc.set.assert_awaited_once()

    def test_list_settings_bad_category(self, client):
        svc = MagicMock()
        _override_service(svc)
        r = client.get("/api/v1/system/settings?category=invalid")
        assert r.status_code == 422  # pattern validation


class TestEnvEndpoints:
    def test_list_envs(self, client):
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[{"id": "1", "name": "dev", "url": "http://x",
                                            "env_type": "dev", "status": "active", "credentials": {}}])
        _override_service(svc)
        r = client.get("/api/v1/system/envs")
        assert r.status_code == 200
        assert r.json()["data"][0]["name"] == "dev"

    def test_create_env(self, client):
        svc = MagicMock()
        svc.create = AsyncMock(return_value={"id": "1", "name": "dev", "url": "http://x",
                                              "env_type": "dev", "status": "active",
                                              "credentials": {}})
        _override_service(svc)
        r = client.post("/api/v1/system/envs",
                        json={"name": "dev", "url": "http://x", "env_type": "dev"})
        assert r.status_code == 201
        assert r.json()["data"]["name"] == "dev"


class TestTokenEndpoints:
    def test_token_status(self, client):
        svc = MagicMock()
        svc.get_status = AsyncMock(return_value=MagicMock(
            model_dump=MagicMock(return_value={
                "total_quota": 100000, "used": 5000, "remaining": 95000,
                "percentage": 5.0, "is_warning": False, "warning_threshold": 10,
                "recent_daily_avg": 1000.0, "estimated_days_remaining": 95,
            })
        ))
        _override_service(svc)
        r = client.get("/api/v1/system/tokens/status?project_id=00000000-0000-0000-0000-000000000001")
        assert r.status_code == 200
        assert r.json()["data"]["used"] == 5000
        assert r.json()["data"]["is_warning"] is False

    def test_token_quota_update(self, client):
        svc = MagicMock()
        svc.update_quota = AsyncMock(return_value={"project_id": "x", "total_quota": 200000,
                                                    "alert_threshold": 10})
        _override_service(svc)
        r = client.put("/api/v1/system/tokens/quota?project_id=00000000-0000-0000-0000-000000000001",
                       json={"total_quota": 200000})
        assert r.status_code == 200


class TestOperationLogEndpoint:
    def test_list_oplogs(self, client):
        svc = MagicMock()
        svc.list = AsyncMock(return_value=([{"id": "1", "module": "system", "action": "x"}], 1))
        _override_service(svc)
        r = client.get("/api/v1/system/operation-logs")
        assert r.status_code == 200
        assert r.json()["data"]["items"][0]["module"] == "system"
