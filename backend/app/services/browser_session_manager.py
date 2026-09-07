"""进程内会话浏览器池（P3 会话式抓取）.

 headed 浏览器活在 FastAPI 进程内存（单 worker + 桌面会话前提），
 release() 只关浏览器保留会话数据，open() 二次调用复用会话（新浏览器导航到新 URL）。
 进程重启丢失（可接受，前端重开即可）。

== 事件循环桥接（Windows 关键） ==
uvicorn --reload 在 Windows 强制 SelectorEventLoop（asyncio_setup(use_subprocess=True)
→ WindowsSelectorEventLoopPolicy），而 SelectorEventLoop **不支持子进程**——
Playwright 的 async_playwright().start() 需要 create_subprocess_exec 启动 driver，
在 Selector loop 上直接 NotImplementedError。

解法：本模块自持一个**专用工作线程 + ProactorEventLoop**（Windows 子进程只有
Proactor 支持），所有 Playwright 操作经 _bridge() 投递到该 loop 执行；
宿主 loop（无论 Proactor 还是 Selector）只做 await 桥接，不碰子进程。
"""
import uuid
import time
import logging
import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Coroutine

from app.services.playwright_service import PlaywrightService

logger = logging.getLogger(__name__)

SESSION_IDLE_TTL = 3600  # 1 小时无操作回收


@dataclass
class BrowserSession:
    session_id: str
    project_id: str
    page: Any = None                    # Playwright Page（浏览器存活时非 None）
    browser: Optional[PlaywrightService] = None
    state: str = "ready"                # ready / awaiting_login / released
    staging_id: Optional[str] = None    # 关联的 P3 CaptureSession（redis staging）
    captured_elements: List[dict] = field(default_factory=list)  # 已抓未入库
    last_active: float = field(default_factory=time.time)

    def touch(self):
        self.last_active = time.time()


class _ProactorBridge:
    """专用后台线程 + ProactorEventLoop：承载所有 Playwright 子进程操作。

    Windows 下 uvicorn --reload 宿主 loop 是 Selector（无子进程能力），
    Proactor 只能在此专用线程创建。首次使用惰性启动；协程经
    run_coroutine_threadsafe 投递，宿主侧 await 结果。
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _ensure_loop(self):
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return
            ready = threading.Event()
            self._loop = None

            def _run():
                loop = asyncio.ProactorEventLoop() if hasattr(
                    asyncio, "ProactorEventLoop") else asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                ready.set()
                loop.run_forever()

            self._thread = threading.Thread(target=_run, daemon=True, name="pw-bridge")
            self._thread.start()
            ready.wait(timeout=10)
            if self._loop is None:
                raise RuntimeError("Failed to start Playwright bridge loop")

    async def run(self, coro: Coroutine) -> Any:
        """把协程投递到桥接 loop 并等待结果（宿主协程内 await）。"""
        self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        # 宿主侧异步等待（不阻塞宿主 loop）
        return await asyncio.wrap_future(fut)

    def run_sync(self, fn, *args, **kwargs) -> Any:
        """把同步函数投递到桥接 loop 执行（包一层协程），供 Mock/同步 API 使用。"""
        return self.run(_async_call(fn, *args, **kwargs))

    def shutdown(self):
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._loop = None
            self._thread = None


async def _async_call(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    # fn 可能返回协程（async 方法 mock）或普通值（同步方法）
    if asyncio.iscoroutine(result):
        return await result
    return result


def _call(fn, *args, **kwargs):
    """包装同步/异步调用为协程，供 _bridge.run 投递。"""
    async def _inner():
        result = fn(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result
    return _inner()


_bridge = _ProactorBridge()


class BrowserSessionManager:
    """单例池（挂 app.state）；每 project 同时最多 1 个会话。

    所有 Playwright 调用经 _bridge.run() 投递到专用 Proactor loop，
    宿主 loop（Selector/Proactor 均可）零子进程依赖。
    """

    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}

    async def open(self, project_id: str, url: str, headless: bool = True,
                   need_login: bool = False) -> str:
        """打开（或复用）会话并导航到 url。need_login=True 时 headless=False 人工登录。"""
        # 同项目复用
        sid = self._find_by_project(project_id)
        if sid is None:
            sid = f"bs_{uuid.uuid4().hex[:12]}"
            self.sessions[sid] = BrowserSession(session_id=sid, project_id=project_id)
        sess = self.sessions[sid]

        # 浏览器不可用（未启动 / 启动失败残留）则（重）启；
        # 之前只判 sess.browser is None，start() 失败后残留 service 对象会导致
        # 复用路径跳过 start，page=None 直接 goto 报错。
        if sess.browser is None or sess.page is None or sess.browser.browser is None:
            if sess.browser is not None:
                try:
                    await _bridge.run(sess.browser.close())
                except Exception:
                    pass
            sess.browser = PlaywrightService()
            await _bridge.run(sess.browser.start(headless=headless))
            # headless: 固定视口 1920x1080（与点选坐标换算 VIEWPORT_WIDTH 一致）；
            # headed: no_viewport 让页面跟随真实窗口大小（用户可最大化/调整窗口），
            # 点选坐标换算用 status 接口返回的实际 innerWidth（前端动态取）
            ctx_kwargs = {} if headless else {"no_viewport": True}
            ctx = await _bridge.run(sess.browser.browser.new_context(**ctx_kwargs))
            sess.page = await _bridge.run(ctx.new_page())
            await _bridge.run(_call(sess.page.set_default_timeout, 30000))

        await _bridge.run(sess.page.goto(url, wait_until="networkidle", timeout=60000))
        sess.touch()
        return sid

    def _find_by_project(self, project_id: str) -> Optional[str]:
        for sid, s in self.sessions.items():
            if s.project_id == project_id:
                return sid
        return None

    async def release(self, session_id: str) -> bool:
        """释放页面：关浏览器，保留会话数据（已抓元素）。用户可接管/稍后重开。"""
        sess = self.sessions.get(session_id)
        if not sess:
            return False
        if sess.browser:
            try:
                await _bridge.run(sess.browser.close())
            except Exception:
                pass
            sess.browser = None
            sess.page = None
        sess.touch()
        return True

    async def close_session(self, session_id: str) -> bool:
        sess = self.sessions.pop(session_id, None)
        if not sess:
            return False
        if sess.browser:
            try:
                await _bridge.run(sess.browser.close())
            except Exception:
                pass
        return True

    def get_page(self, session_id: str):
        return self.sessions[session_id].page if session_id in self.sessions else None

    def get_session(self, session_id: str) -> Optional[BrowserSession]:
        return self.sessions.get(session_id)

    async def reap_idle(self):
        """定时回收：空闲超 TTL 的会话关浏览器保留数据（由 lifespan 启动后台任务调用）"""
        now = time.time()
        for sid, s in list(self.sessions.items()):
            if now - s.last_active > SESSION_IDLE_TTL and s.browser:
                await self.release(sid)
