"""元素选择器数据源端点测试（方案V1，Cypress 选择器交互）。

按仓库无 ASGI client fixture 的现状，用 TestClient(app) + dependency_overrides
风格（照 tests/test_api_elements.py），service 层用 patch。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.services.element_service import ElementService

PID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


def test_picker_returns_grouped_elements(client):
    fake = {"pages": [{"page_id": "p1", "page_name": "登录页",
                       "elements": [{"element_id": "el-1", "element_name": "请输入账号",
                                     "locator": "#zh", "confidence": 5}]}]}
    with patch.object(ElementService, "picker_data",
                      new=AsyncMock(return_value=fake)):
        r = client.get("/api/v1/elements/picker",
                       params={"project_id": PID, "q": "账号"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["pages"][0]["elements"][0]["element_name"] == "请输入账号"


def test_picker_requires_project(client):
    r = client.get("/api/v1/elements/picker")
    assert r.status_code == 422
