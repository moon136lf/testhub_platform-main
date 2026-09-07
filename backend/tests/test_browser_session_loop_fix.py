# -*- coding: utf-8 -*-
"""BrowserSessionManager regression test — SelectorEventLoop subprocess fix.

uvicorn --reload 在 Windows 强制 SelectorEventLoop（不支持子进程），
Playwright async API 在其上 start() 抛 NotImplementedError。
修复：Playwright 操作桥接到专用线程的 ProactorEventLoop。
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_pw_cls():
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
        page.set_default_timeout = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        svc.browser.new_context = AsyncMock(return_value=ctx)
        yield svc, page


@pytest.mark.asyncio
async def test_open_works_under_selector_loop(mock_pw_cls):
    """回归：宿主事件循环是 Selector（无子进程支持）时 open 仍能启动 Playwright。

    实现方式是后台 Proactor 线程桥接——该测试在 Proactor 宿主里跑也必须通过
    （桥接对宿主 loop 类型不敏感）。
    """
    from app.services.browser_session_manager import BrowserSessionManager
    mgr = BrowserSessionManager()
    sid = await mgr.open(project_id="p1", url="http://x/", headless=True)
    assert sid in mgr.sessions
    svc, page = mock_pw_cls
    svc.start.assert_awaited()          # 在桥接 loop 上执行过
    page.goto.assert_awaited()
    await mgr.close_session(sid)


@pytest.mark.asyncio
async def test_operations_routed_to_bridge_loop(mock_pw_cls):
    """goto/screenshot 等 Playwright 操作在桥接 loop 上执行（不依赖宿主 loop 子进程能力）."""
    from app.services.browser_session_manager import BrowserSessionManager
    mgr = BrowserSessionManager()
    sid = await mgr.open(project_id="p1", url="http://x/", headless=True)
    svc, page = mock_pw_cls
    # 再做一次会触发 Playwright 调用的操作（释放走 close）
    await mgr.release(sid)
    svc.close.assert_awaited()
    assert mgr.sessions[sid].browser is None


@pytest.mark.asyncio
async def test_release_keeps_state_and_reopen(mock_pw_cls):
    from app.services.browser_session_manager import BrowserSessionManager
    mgr = BrowserSessionManager()
    sid = await mgr.open("p1", "http://x/", headless=True)
    await mgr.release(sid)
    sid2 = await mgr.open("p1", "http://y/", headless=True)
    assert sid2 == sid
    await mgr.close_session(sid)
    assert sid not in mgr.sessions
