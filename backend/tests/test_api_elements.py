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


def test_import_endpoint_maps_element_data(client):
    """/import: ElementData pydantic 对象 → batch_import dict 契约映射 (P1 修复回归).

    回归背景: 端点曾用 elem.get("temp_id") 访问 pydantic 对象 → AttributeError 500。
    """
    payload = {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "page_name": "导入测试页", "page_url": "http://import-test/",
        "selected_element_ids": ["e1"],
        "elements_data": [{
            "temp_id": "e1", "element_type": "button", "element_text": "刷新",
            "locator_strategies": {"strategies": [
                {"type": "css", "value": "#refresh", "score": 120, "unique": True}]},
            "semantic_info": {"type": "button", "text": "刷新",
                              "coords": {"x": 1, "y": 2, "width": 3, "height": 4},
                              "context": {}},
            "position_x": 1, "position_y": 2, "width": 3, "height": 4,
            "attributes": {"id": "refresh"},
        }],
        "screenshot_url": "http://x/s.png",
    }
    # mock db: create_page 返回带 id 的 page; batch_import 走真实逻辑但 db 为 mock
    # 参照 login-state 测试的 override 风格
    from unittest.mock import AsyncMock, MagicMock, patch
    fake_page = MagicMock()
    fake_page.id = "p1"
    with patch("app.services.element_service.ElementService.create_page", new=AsyncMock(return_value=fake_page)), \
         patch("app.services.element_service.ElementService.batch_import_elements", new=AsyncMock(return_value=[MagicMock(element_name="刷新")])):
        r = client.post("/api/v1/elements/import", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["imported_count"] == 1
