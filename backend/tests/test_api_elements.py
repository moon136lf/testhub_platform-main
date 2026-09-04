"""Element API tests — login-state placeholder (P1 T3)."""
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


def _override_db(mock_db):
    from app.core.database import get_db
    app.dependency_overrides[get_db] = lambda: mock_db


def test_login_state_not_configured(client):
    """P1: login_state 表未建/无行 → not_configured 占位."""
    db = MagicMock()
    result = MagicMock()
    result.first.return_value = None
    db.execute = AsyncMock(return_value=result)
    _override_db(db)
    r = client.get(f"/api/v1/elements/login-state?project_id={PID}")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "not_configured"
    assert "cookie_count" in d and "localstorage_count" in d
