"""会话式抓取端点测试 (#elem-p3w T2) — open/status/capture/pick/release/close.

mock app.api.v1.elements.browser_mgr（进程内 BrowserSessionManager 单例），
不启动真实浏览器。
"""
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

PID = "00000000-0000-0000-0000-000000000001"
SID = "bs_abc123"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mgr():
    m = MagicMock()
    m.open = AsyncMock(return_value=SID)
    m.release = AsyncMock(return_value=True)
    m.close_session = AsyncMock(return_value=True)
    m.get_page = MagicMock(return_value=None)
    m.get_session = MagicMock(return_value=_fake_session())
    with patch("app.api.v1.elements.browser_mgr", m):
        yield m


def _fake_session(state="ready", page=None):
    s = MagicMock()
    s.project_id = PID
    s.state = state
    s.page = page
    return s


def _fake_page(url="http://x/login"):
    p = MagicMock()
    p.url = url
    p.title = AsyncMock(return_value="登录页")
    p.screenshot = AsyncMock(return_value=b"png")
    return p


# ---------------- open ----------------

def test_open_session_need_login(client, mgr):
    r = client.post("/api/v1/elements/capture/browser/open", json={
        "project_id": PID, "url": "http://x/admin", "need_login": True,
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["session_id"] == SID
    assert d["state"] == "awaiting_login"
    _, kwargs = mgr.open.call_args
    assert kwargs.get("headless") is False


def test_open_session_no_login(client, mgr):
    r = client.post("/api/v1/elements/capture/browser/open", json={
        "project_id": PID, "url": "http://x/admin", "need_login": False,
    })
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["state"] == "ready"
    _, kwargs = mgr.open.call_args
    assert kwargs.get("headless") is True


def test_open_session_bad_project(client, mgr):
    r = client.post("/api/v1/elements/capture/browser/open", json={
        "project_id": "not-a-uuid", "url": "http://x/",
    })
    assert r.status_code == 400


# ---------------- status ----------------

def test_status_returns_screenshot(client, mgr):
    page = _fake_page(url="http://x/admin")
    mgr.get_session.return_value = _fake_session(state="ready", page=page)
    r = client.get(f"/api/v1/elements/capture/browser/{SID}/status")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["state"] == "ready"
    assert d["url"] == "http://x/admin"
    assert d["title"] == "登录页"
    assert d["screenshot_b64"] == base64.b64encode(b"png").decode()


def test_status_awaiting_login_still_on_login_page(client, mgr):
    page = _fake_page(url="http://x/login")
    sess = _fake_session(state="awaiting_login", page=page)
    mgr.get_session.return_value = sess
    r = client.get(f"/api/v1/elements/capture/browser/{SID}/status")
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "awaiting_login"


def test_status_awaiting_login_left_login_page(client, mgr):
    page = _fake_page(url="http://x/dashboard")
    sess = _fake_session(state="awaiting_login", page=page)
    mgr.get_session.return_value = sess
    r = client.get(f"/api/v1/elements/capture/browser/{SID}/status")
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "ready"
    assert sess.state == "ready"


def test_status_released_session(client, mgr):
    # 会话存在但浏览器已释放（release 后 page=None）
    mgr.get_session.return_value = _fake_session(state="released", page=None)
    r = client.get(f"/api/v1/elements/capture/browser/{SID}/status")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["state"] == "released"
    assert d["screenshot_b64"] is None


# ---------------- capture ----------------

def _element_dict(temp_id="elem_0_aaa"):
    return {
        "temp_id": temp_id,
        "element_type": "button",
        "element_text": "登录",
        "locator_strategies": {"strategies": [
            {"type": "css", "value": "#login", "score": 120, "unique": True, "verified": True}]},
        "semantic_info": {"type": "button", "text": "登录",
                          "coords": {"x": 1, "y": 2, "width": 3, "height": 4},
                          "context": {}},
        "position_x": 1, "position_y": 2, "width": 3, "height": 4,
        "attributes": {"id": "login"},
    }


def test_capture_adds_to_staging(client, mgr):
    page = _fake_page(url="http://x/admin")
    sess = _fake_session(state="ready", page=page)
    sess.staging_id = None
    mgr.get_page.return_value = page
    mgr.get_session.return_value = sess
    with patch("app.api.v1.elements.scan_interactive_elements", new=AsyncMock(return_value=[MagicMock()])), \
         patch("app.api.v1.elements._verify_elements", new=AsyncMock(return_value=[_element_dict(), _element_dict("elem_1_bbb")])), \
         patch("app.core.storage.storage_client.upload_bytes", new=AsyncMock(return_value="http://minio/s.png")), \
         patch("app.services.capture_session_service.CaptureSessionService.get", new=AsyncMock(return_value=None)), \
         patch("app.services.capture_session_service.CaptureSessionService.create",
               new=AsyncMock(return_value={"session_id": "cap_x", "project_id": PID})), \
         patch("app.services.capture_session_service.CaptureSessionService.add_batch",
               new=AsyncMock(return_value={"batch_idx": 0, "batch_count": 1, "added": 2, "total_elements": 2})) as add_batch:
        r = client.post(f"/api/v1/elements/capture/browser/{SID}/capture")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["total_count"] == 2
    assert len(d["elements"]) == 2
    assert d["batch_idx"] == 0
    assert d["staging_session_id"] == "cap_x"
    assert sess.staging_id == "cap_x"
    # add_batch 收到截图 URL
    assert add_batch.call_args.args[2] == "http://minio/s.png"


def test_capture_reuses_existing_staging(client, mgr):
    page = _fake_page(url="http://x/admin")
    sess = _fake_session(state="ready", page=page)
    sess.staging_id = "cap_exists"
    mgr.get_page.return_value = page
    mgr.get_session.return_value = sess
    with patch("app.api.v1.elements.scan_interactive_elements", new=AsyncMock(return_value=[])), \
         patch("app.api.v1.elements._verify_elements", new=AsyncMock(return_value=[])), \
         patch("app.core.storage.storage_client.upload_bytes", new=AsyncMock(return_value="http://minio/s.png")), \
         patch("app.services.capture_session_service.CaptureSessionService.get",
               new=AsyncMock(return_value={"session_id": "cap_exists"})), \
         patch("app.services.capture_session_service.CaptureSessionService.create", new=AsyncMock()) as create, \
         patch("app.services.capture_session_service.CaptureSessionService.add_batch",
               new=AsyncMock(return_value={"batch_idx": 1, "batch_count": 2, "added": 0, "total_elements": 3})):
        r = client.post(f"/api/v1/elements/capture/browser/{SID}/capture")
    assert r.status_code == 200
    create.assert_not_called()
    assert r.json()["data"]["staging_session_id"] == "cap_exists"


def test_capture_no_page(client, mgr):
    mgr.get_page.return_value = None
    r = client.post(f"/api/v1/elements/capture/browser/{SID}/capture")
    assert r.status_code == 404


# ---------------- pick-element ----------------

def test_pick_element_hit(client, mgr):
    page = _fake_page(url="http://x/admin")
    mgr.get_page.return_value = page
    el = _element_dict("elem_pick_1")
    el["locator_strategies"]["strategies"][0]["value"] = "[data-pick-hit='1']"
    with patch("app.api.v1.elements._pick_element_via_dom", new=AsyncMock(return_value=el)):
        r = client.post(f"/api/v1/elements/capture/browser/{SID}/pick-element",
                        json={"x": 100.0, "y": 200.0})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["element"]["element_text"] == "登录"
    assert d["element"]["locator_strategies"]["strategies"][0]["value"]


def test_pick_element_no_hit(client, mgr):
    page = _fake_page(url="http://x/admin")
    mgr.get_page.return_value = page
    with patch("app.api.v1.elements._pick_element_via_dom", new=AsyncMock(return_value=None)):
        r = client.post(f"/api/v1/elements/capture/browser/{SID}/pick-element",
                        json={"x": 1.0, "y": 2.0})
    assert r.status_code == 404


# ---------------- release / close ----------------

def test_release_keeps_session(client, mgr):
    r = client.post(f"/api/v1/elements/capture/browser/{SID}/release")
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "released"
    mgr.release.assert_awaited_once_with(SID)


def test_close_session(client, mgr):
    r = client.post(f"/api/v1/elements/capture/browser/{SID}/close")
    assert r.status_code == 200
    assert r.json()["data"]["closed"] is True
    mgr.close_session.assert_awaited_once_with(SID)


# ---------------- 未知 session ----------------

def test_session_not_found(client, mgr):
    mgr.get_session.return_value = None
    mgr.get_page.return_value = None
    assert client.get(f"/api/v1/elements/capture/browser/{SID}/status").status_code == 404
    assert client.post(f"/api/v1/elements/capture/browser/{SID}/capture").status_code == 404
    assert client.post(f"/api/v1/elements/capture/browser/{SID}/pick-element",
                       json={"x": 1, "y": 2}).status_code == 404
    assert client.post(f"/api/v1/elements/capture/browser/{SID}/release").status_code == 404
    assert client.post(f"/api/v1/elements/capture/browser/{SID}/close").status_code == 404


# ---------------- 集成：真实 BrowserSession 状态机（不预 mock state） ----------------

def test_awaiting_login_state_machine(client, mgr):
    """open(need_login=True) 在真实 BrowserSession 上持久化 state；
    status 按 URL 轻校验推进 awaiting_login → ready。"""
    # browser_mgr 为 mock，但让 open() 创建真实 BrowserSession 对象
    from app.services.browser_session_manager import BrowserSession
    real_sess = BrowserSession(session_id=SID, project_id=PID)
    mgr.open = AsyncMock(side_effect=lambda *a, **k: SID)
    mgr.get_session = MagicMock(return_value=real_sess)
    real_sess.page = _fake_page(url="http://x/login")

    r = client.post("/api/v1/elements/capture/browser/open", json={
        "project_id": PID, "url": "http://x/login", "need_login": True,
    })
    assert r.status_code == 200
    assert real_sess.state == "awaiting_login"

    r = client.get(f"/api/v1/elements/capture/browser/{SID}/status")
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "awaiting_login"  # 仍在 login URL

    # 模拟登录完成：URL 离开登录页
    real_sess.page.url = "http://x/dashboard"
    r = client.get(f"/api/v1/elements/capture/browser/{SID}/status")
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "ready"
    assert real_sess.state == "ready"
