"""进程内会话浏览器池（P3 会话式抓取）.

 headed 浏览器活在 FastAPI 进程内存（单 worker + 桌面会话前提），
 release() 只关浏览器保留会话数据，open() 二次调用复用会话（新浏览器导航到新 URL）。
 进程重启丢失（可接受，前端重开即可）。
"""
import uuid
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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


class BrowserSessionManager:
    """单例池（挂 app.state）；每 project 同时最多 1 个会话"""

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
                    await sess.browser.close()
                except Exception:
                    pass
            sess.browser = PlaywrightService()
            await sess.browser.start(headless=headless)
            ctx = await sess.browser.browser.new_context()
            sess.page = await ctx.new_page()
            sess.page.set_default_timeout(30000)

        await sess.page.goto(url, wait_until="networkidle", timeout=60000)
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
                await sess.browser.close()
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
                await sess.browser.close()
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
