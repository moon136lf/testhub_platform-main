"""BrowserSessionManager tests — 进程内会话浏览器池."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_pw():
    """PlaywrightService 桩: start/close/browser.new_context 全 mock."""
    with patch("app.services.browser_session_manager.PlaywrightService") as cls:
        svc = cls.return_value
        svc.start = AsyncMock()
        svc.close = AsyncMock()
        ctx = MagicMock()
        page = MagicMock()
        page.goto = AsyncMock()
        page.url = "http://x/"
        page.title = AsyncMock(return_value="T")
        page.screenshot = AsyncMock(return_value=b"png")
        ctx.new_page = AsyncMock(return_value=page)
        svc.browser.new_context = AsyncMock(return_value=ctx)
        yield svc, page


@pytest.mark.asyncio
async def test_open_session_headed(mock_pw):
    from app.services.browser_session_manager import BrowserSessionManager
    mgr = BrowserSessionManager()
    sid = await mgr.open(project_id="p1", url="http://x/", headless=False)
    svc, page = mock_pw
    svc.start.assert_awaited_once_with(headless=False)
    page.goto.assert_awaited_once()
    assert sid in mgr.sessions
    assert mgr.sessions[sid].page is page


@pytest.mark.asyncio
async def test_release_keeps_session_state(mock_pw):
    """释放页面 = 关浏览器但会话状态（已抓元素）保留."""
    from app.services.browser_session_manager import BrowserSessionManager
    mgr = BrowserSessionManager()
    sid = await mgr.open("p1", "http://x/", headless=True)
    mgr.sessions[sid].captured_elements = [{"temp_id": "t1"}]
    await mgr.release(sid)
    svc, _ = mock_pw
    svc.close.assert_awaited_once()
    assert sid in mgr.sessions  # 会话还在
    assert mgr.sessions[sid].browser is None
    assert mgr.sessions[sid].captured_elements == [{"temp_id": "t1"}]  # 数据保留


@pytest.mark.asyncio
async def test_reopen_reuses_session(mock_pw):
    """释放后再 open = 同一 session 复用（新浏览器）."""
    from app.services.browser_session_manager import BrowserSessionManager
    mgr = BrowserSessionManager()
    sid = await mgr.open("p1", "http://x/", headless=True)
    await mgr.release(sid)
    sid2 = await mgr.open("p1", "http://y/", headless=True)
    assert sid2 == sid
    svc, page = mock_pw
    assert page.goto.await_count == 2  # 二次导航


@pytest.mark.asyncio
async def test_close_session(mock_pw):
    from app.services.browser_session_manager import BrowserSessionManager
    mgr = BrowserSessionManager()
    sid = await mgr.open("p1", "http://x/", headless=True)
    await mgr.close_session(sid)
    assert sid not in mgr.sessions
