"""静态扫描 API：zip 上传校验（大小/扩展名/路径穿越条目）+ 静态元素列表"""
import io, zipfile
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app

PID = "00000000-0000-0000-0000-000000000001"
SCAN = "22222222-2222-2222-2222-222222222222"


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


def _zip_bytes(*names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "<template><button>x</button></template>")
    return buf.getvalue()


class TestLocatorScanUpload:
    def test_upload_ok(self, client):
        svc = MagicMock()
        svc.create_scan = AsyncMock(return_value={"id": SCAN, "status": "scanning"})
        _override(svc)
        with patch("app.tasks.code_scan_tasks.run_locator_scan_task") as mock_task:
            mock_task.delay = MagicMock()
            r = client.post("/api/v1/whitescan/locator-scan",
                            files={"file": ("front.zip", _zip_bytes("src/A.vue"), "application/zip")},
                            data={"project_id": PID})
        assert r.status_code == 200
        assert r.json()["data"]["scan_id"] == SCAN
        mock_task.delay.assert_called_once()

    def test_reject_non_zip(self, client):
        r = client.post("/api/v1/whitescan/locator-scan",
                        files={"file": ("x.txt", b"hello", "text/plain")},
                        data={"project_id": PID})
        assert r.status_code == 400

    def test_reject_path_traversal(self, client):
        r = client.post("/api/v1/whitescan/locator-scan",
                        files={"file": ("evil.zip", _zip_bytes("../evil.vue"), "application/zip")},
                        data={"project_id": PID})
        assert r.status_code == 400

    def test_reject_oversize(self, client):
        big = b"\0" * (51 * 1024 * 1024)
        r = client.post("/api/v1/whitescan/locator-scan",
                        files={"file": ("big.zip", big, "application/zip")},
                        data={"project_id": PID})
        assert r.status_code == 400


class TestStaticElements:
    def test_list_static_elements(self, client):
        svc = MagicMock()
        svc.list_static_elements = AsyncMock(return_value={
            "total": 1, "items": [{"file_path": "src/A.vue", "component_name": "A",
                                    "element_count": 3, "ai_generated": True, "reused": False}]})
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans/{SCAN}/static-elements")
        assert r.status_code == 200
        assert r.json()["data"]["items"][0]["component_name"] == "A"
