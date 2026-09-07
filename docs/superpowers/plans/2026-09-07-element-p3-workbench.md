# 元素库会话式抓取交互重构（P3 终态）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 实现用户确认的会话式抓取终态流程——headed 浏览器人工登录、浏览器保持、点选补抓、页面树层级、独立入库、别名默认中文、已入库元素列表区。

**需求存档:** 快照 #57（9 点需求）+ memory `moontest-element-p3-workbench`；spec：`docs/superpowers/specs/2026-09-03-element-enhancement-design.md` §2.3。

**已有资产（复用）:** `capture_session_service.py`（Redis 暂存）、`CaptureWorkbench.vue`、`ElementHighlight.vue`、`scan_interactive_elements`/`generate_locators_for_element`/`verify_and_score_locator`/`extract_semantic_info`、`PlaywrightService(start(headless=False))`、SSE 直播链路。

**核心架构决策（已确认）:** 会话浏览器活在 FastAPI 进程内存（`app.state`），单 worker；headed 必须桌面会话；点选补抓用 elementFromPoint 活 DOM 反查。

---

### Task 1: BrowserSessionManager（进程内会话浏览器池）

**Files:**
- Create: `backend/app/services/browser_session_manager.py`
- Test: `backend/tests/test_browser_session_manager.py`

- [ ] Step 1: 失败测试（mock PlaywrightService）

```python
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
```

- [ ] Step 2: 确认失败

- [ ] Step 3: 实现 `BrowserSessionManager`

```python
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

        if sess.browser is None:
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
```

- [ ] Step 4: 测试绿 → Commit `feat(elements): BrowserSessionManager — in-process session browser pool (#elem-p3w T1)`

---

### Task 2: 会话式抓取端点（open/login-status/capture/pick/release）

**Files:**
- Modify: `backend/app/api/v1/elements.py`（追加 6 个端点）
- Modify: `backend/app/main.py`（lifespan 挂 manager 单例 + reap 后台任务）
- Test: `backend/tests/test_api_capture_session.py`（新建）

- [ ] Step 1: 失败测试（参照 test_api_elements.py 的 TestClient + override 风格，patch `app.api.v1.elements.browser_mgr`）

覆盖：
1. `POST /capture/browser/open` `{project_id, url, need_login}` → 200 `{session_id, state}`；need_login 时 state="awaiting_login"，否则 "ready"
2. `GET /capture/browser/{sid}/status` → `{state, url, title, screenshot_b64}`（screenshot 从 page.screenshot）
3. `POST /capture/browser/{sid}/capture` → 复用 scan+verify+extract 流水线（同 element_tasks 阶段5），结果**追加进 CaptureSessionService**（复用 P3 redis staging）并返回元素
4. `POST /capture/browser/{sid}/pick-element` `{x, y}` → elementFromPoint 反查 + 五策略评分 → 定位卡片数据
5. `POST /capture/browser/{sid}/release` → 释放浏览器保留会话
6. `POST /capture/browser/{sid}/close` → 关闭整个会话

- [ ] Step 2: 确认失败 → 实现

要点：
- `elements.py` 顶部 `from app.services.browser_session_manager import BrowserSessionManager; browser_mgr = BrowserSessionManager()`（模块级单例）
- pick-element 核心调用（在端点内）：
```python
page = browser_mgr.get_page(sid)
el = await page.evaluate(
    "([x, y]) => { const e = document.elementFromPoint(x, y);"
    " if (!e) return null;"
    " e.setAttribute('data-pick-hit', '1');"
    " return {tag: e.tagName.toLowerCase(), text: (e.innerText||'').slice(0,100)}; }",
    [x, y])
# 命中后用 page.locator("[data-pick-hit='1']") 拿 Locator → 复用 generate/verify/extract → 移除标记
```
- capture 端点内联复用 element_tasks 的阶段5流水线（抽公共函数 `_verify_elements(page, raw_elements)` 到 element_tasks 或直接内联——选抽公共函数放 playwright_locator_core 或新 helper，避免复制 60 行）
- main.py lifespan：`app.state.browser_mgr = browser_mgr`；`asyncio.create_task` 周期 reap（60s 间隔，shutdown 时 cancel）
- need_login 流程 v1 简化：state="awaiting_login" 时前端展示「请在浏览器中完成登录，然后点 [登录完成]」按钮 → 调 status 确认 URL 离开登录页 → state→ready（轻量校验按 spec：URL 含 login/signin/auth 判未过）

- [ ] Step 3: 测试绿 + 既有全量不回归
- [ ] Step 4: Commit `feat(elements): session browser endpoints — open/status/capture/pick/release (#elem-p3w T2)`

---

### Task 3: 前端工作台重构（会话式 tab 主循环）

**Files:**
- Modify: `frontend/src/components/element/CaptureWorkbench.vue`（重写为主循环工作台）
- Modify: `frontend/src/api/element.js`（+5 方法）
- Modify: `frontend/src/views/ElementLibrary.vue`（会话 tab 流程串联）

- [ ] Step 1: element.js 新增

```js
async openBrowserSession(data) {   // {project_id, url, need_login}
    const response = await axios.post('/elements/capture/browser/open', data)
    return response.data
},
async getBrowserStatus(sessionId) {
    const response = await axios.get(`/elements/capture/browser/${sessionId}/status`)
    return response.data
},
async captureBrowserPage(sessionId) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/capture`)
    return response.data
},
async pickBrowserElement(sessionId, x, y) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/pick-element`, { x, y })
    return response.data
},
async releaseBrowser(sessionId) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/release`)
    return response.data
},
```

- [ ] Step 2: CaptureWorkbench 重写为状态机视图

```
state: idle → awaiting_login → ready → capturing(短暂) → ready
├─ idle: [开始] 表单（URL + 是否需要登录开关）
├─ awaiting_login: 蓝横幅「已弹出浏览器，请完成登录后点击下方按钮」+ [✅ 登录完成]（调 status 轻校验）+ [强制继续] + [取消]
├─ ready: 双栏
│   左：浏览器实时截图（status 接口的 screenshot_b64，轮询 3s 或每次操作后刷新）+ [开始抓取元素] 按钮
│   右：已抓元素列表（CaptureSessionService staging 数据，勾选/删除/全选沿用现有）
│        + [点选补抓] 开关（开启后点截图坐标 → pick-element → 定位卡片 → 加入列表）
│        + [释放页面]（关浏览器保留数据，可再 open）+ [入库]（沿用现有入库表单，独立每次入库）
```

- [ ] Step 3: ElementLibrary.vue 会话 tab 串联（原 handleSessionFetchClick 改调 workbench.open 流程；工作台 imported 事件后刷新列表）
- [ ] Step 4: vite build 绿
- [ ] Step 5: Commit `feat(elements): workbench main loop — headed login/keep-alive/pick-补抓 (#elem-p3w T3)`

---

### Task 4: 页面树层级 + 别名默认中文

**Files:**
- Modify: `backend/migrations/element_page_hierarchy.sql`（新迁移：page_repository + parent_id）
- Modify: `backend/app/models/element.py`（PageRepository + parent_id）
- Modify: `backend/app/services/element_service.py`（create_page 加 parent_id；别名生成 helper）
- Modify: `frontend/src/components/element/FetchDialog.vue` / CaptureWorkbench 入库表单（父页面下拉）
- Modify: `frontend/src/views/ElementLibrary.vue`（页面树 el-tree + 已入库元素列表区：近7日筛选 + 刷新）

- [ ] Step 1: 迁移 SQL（幂等）
```sql
ALTER TABLE page_repository ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES page_repository(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_page_repository_parent ON page_repository(parent_id);
```
- [ ] Step 2: 别名默认中文：入库时 element_name 生成逻辑——优先级：用户填 > aria_label > placeholder > element_text > `{类型中文}{序号}`（类型中文映射：button→按钮/input→输入框/link→链接/select→下拉框/span→文本/other→元素）。在 batch_import_elements 内实现（element_service.py）
- [ ] Step 3: 页面树：`GET /pages` 返回加 children 结构（或前端按 parent_id 组树）；入库弹窗父页面下拉（el-tree-select 或级联）
- [ ] Step 4: 已入库元素列表区（元素库首页新卡片）：`GET /pages/{id}/elements` 已有；近7日筛选（created_at >= now-7d 参数）+ 刷新按钮；左页面树点击切换
- [ ] Step 5: 测试（迁移 SQL 幂等跑一次验证 + 别名生成测试 + 树组装测试）→ 全量绿
- [ ] Step 6: Commit `feat(elements): page hierarchy + chinese alias defaults + elements list area (#elem-p3w T4)`

---

### Task 5: 端到端验证 + 收尾

- [ ] Step 1: 全量后端测试 + vite build
- [ ] Step 2: 真实流程验证（controller 协助用户）：抓 localhost:3000 需登录开关关 → 抓取 → 勾选入库 → 别名中文 → 页面树层级 → 点选补抓一个漏掉元素 → 释放页面 → 再开抓第二页
- [ ] Step 3: 验收 checklist 对照需求 9 点逐条勾
- [ ] Step 4: Commit（如有 fixup）+ 更新快照

---

## 风险与注意
- **headed 浏览器在 API 进程**：`--reload` 会杀会话（开发期可接受）；uvicorn 必须跑在桌面会话（不能是 Windows 服务）
- **capture 端点在 API 进程直接跑 Playwright**：不再走 Celery——scan/verify 是 IO 密集，单页面秒级，同步等待可接受（前端按钮 loading）
- **pick-element 的 data-pick-hit 标记**：evaluate 内 setAttribute 有 XSS 面吗？无——值是常量字符串，定位靠 attribute selector
- **并行会话**：每 project 限 1 个（open 复用逻辑已含）；不同 project 可并存
- **另一会话的未提交文件**：绝不触碰（sse.py 虽然相关但属于另一会话的未提交改动，基于已提交版本工作即可——Task 1-2 不需要改 sse.py）
