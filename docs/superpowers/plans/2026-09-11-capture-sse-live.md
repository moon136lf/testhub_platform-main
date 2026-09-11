# 会话式抓取 SSE 直播 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 会话式抓取「开始抓取元素」加 SSE 直播——消息流 + 进度条 + 按选择器轮的元素计数，对齐一次性抓取体验。

**Architecture:** 进程内 SSE（不套 Celery）：capture 端点直接 `SSEStream(sid).send_message(...)` 写 Redis List，前端 EventSource 订阅既有 `/api/sse/element-fetch/{sid}` 通道；`scan_interactive_elements` 加可选 `on_progress` 回调按轮播报计数。

**Tech Stack:** FastAPI + Redis SSE / Vue3 / pytest（基线 802）

**Spec:** `docs/superpowers/specs/2026-09-11-capture-sse-live-design.md`

**测试基线:** `cd /d/MoonTest/backend && python -m pytest -q` → 802 passed

---

### Task 1: 扫描器 on_progress 回调

**Files:**
- Modify: `backend/app/services/playwright_locator_core.py`（scan_interactive_elements）
- Test: `backend/tests/test_element_scanning.py`

- [ ] **Step 1: 写失败测试**

在 test_element_scanning.py 的 TestScanInteractiveElements 类末尾追加：

```python
    @pytest.mark.asyncio
    async def test_on_progress_called_per_selector_round(self):
        """传 on_progress 时每轮扫描完回调一次 (selector, 累计数)"""
        from unittest.mock import patch
        button = _make_elem(visible=True, box={"x": 1, "y": 1, "width": 10, "height": 10})
        span = _make_elem(visible=True, box={"x": 2, "y": 2, "width": 10, "height": 10})
        span.inner_text = AsyncMock(return_value="文本")

        def locator_factory(selector):
            mock_loc = AsyncMock()
            if selector == "button":
                mock_loc.all = AsyncMock(return_value=[button])
            elif selector == "span":
                mock_loc.all = AsyncMock(return_value=[span])
            else:
                mock_loc.all = AsyncMock(return_value=[])
            return mock_loc

        page = AsyncMock()
        page.locator = MagicMock(side_effect=locator_factory)
        calls = []

        async def on_progress(selector, total):
            calls.append((selector, total))

        with patch("app.services.playwright_locator_core.INTERACTIVE_SELECTORS", ["button"]), \
             patch("app.services.playwright_locator_core.TEXT_SELECTORS", ["span"]):
            result = await scan_interactive_elements(page, include_text=True, on_progress=on_progress)

        assert len(result) == 2
        # 每轮一次：button 轮累计 1，span 轮累计 2
        assert ("button", 1) in calls
        assert ("span", 2) in calls
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_on_progress_none_by_default(self):
        """缺省 on_progress=None 行为不变（回调不被调用）"""
        from unittest.mock import patch
        page = AsyncMock()
        page.locator = MagicMock(side_effect=lambda sel: AsyncMock(all=AsyncMock(return_value=[])))
        calls = []

        async def on_progress(selector, total):
            calls.append((selector, total))

        with patch("app.services.playwright_locator_core.INTERACTIVE_SELECTORS", []), \
             patch("app.services.playwright_locator_core.TEXT_SELECTORS", []):
            await scan_interactive_elements(page, on_progress=None)
        assert calls == []

    @pytest.mark.asyncio
    async def test_on_progress_exception_swallowed(self):
        """回调抛异常不中断扫描"""
        from unittest.mock import patch
        button = _make_elem(visible=True, box={"x": 1, "y": 1, "width": 10, "height": 10})

        def locator_factory(selector):
            mock_loc = AsyncMock()
            if selector == "button":
                mock_loc.all = AsyncMock(return_value=[button])
            else:
                mock_loc.all = AsyncMock(return_value=[])
            return mock_loc

        page = AsyncMock()
        page.locator = MagicMock(side_effect=locator_factory)

        async def bad_progress(selector, total):
            raise RuntimeError("boom")

        with patch("app.services.playwright_locator_core.INTERACTIVE_SELECTORS", ["button"]), \
             patch("app.services.playwright_locator_core.TEXT_SELECTORS", []):
            result = await scan_interactive_elements(page, on_progress=bad_progress)
        assert len(result) == 1
```

- [ ] **Step 2: 跑红**

`cd /d/MoonTest/backend && python -m pytest tests/test_element_scanning.py -k on_progress -x -q` → FAIL（unexpected keyword 'on_progress'）

- [ ] **Step 3: 实现**

playwright_locator_core.py `scan_interactive_elements` 签名加 `on_progress=None`：

```python
async def scan_interactive_elements(
    page, include_text: bool = False, include_div_text: bool = False,
    on_progress=None,
) -> List[Any]:
```

docstring 补：`on_progress: 可选回调 (selector, running_total)，每轮选择器扫描完调用一次（SSE 按轮计数用）；回调异常被吞掉不中断扫描`

两个内嵌函数（scan_selectors / scan_div_text_selectors）的 selector 循环末尾（`except Exception: continue` 所在 try 块之后、for 下一轮之前）加：

```python
            if on_progress:
                try:
                    await on_progress(selector, len(elements))
                except Exception:
                    pass
```

- [ ] **Step 4: 绿 + 回归 → Commit**

`python -m pytest tests/test_element_scanning.py -q` 全 PASS；`python -m pytest -q` 全 PASS（802+3）

```bash
git add backend/app/services/playwright_locator_core.py backend/tests/test_element_scanning.py
git commit -m "feat(elements): 扫描器加on_progress按轮计数回调(会话抓取SSE直播用)"
```

---

### Task 2: capture 端点发 SSE 消息

**Files:**
- Modify: `backend/app/api/v1/elements.py`（capture_browser_page）
- Test: `backend/tests/test_api_capture_session.py`

- [ ] **Step 1: 写失败测试**

在 test_api_capture_session.py 追加（照抄 test_capture_passes_include_div_text 的 patch 集合）：

```python
def test_capture_emits_sse_messages(client, mgr):
    """capture 端点应发 SSE 直播消息（开始/按轮计数/完成 progress=1.0）"""
    async def fake_scan(page, include_text=False, include_div_text=True, on_progress=None):
        if on_progress:
            await on_progress("button", 2)
        return []

    fake_elem = MagicMock()
    with patch("app.api.v1.elements.scan_interactive_elements", new=fake_scan), \
         patch("app.api.v1.elements._verify_elements", new=AsyncMock(return_value=[
             {"temp_id": "t1", "element_type": "button", "element_text": "x",
              "locator_strategies": {"strategies": []},
              "semantic_info": {"coords": {"x": 1, "y": 2, "width": 3, "height": 4}},
              "position_x": 1, "position_y": 2, "width": 3, "height": 4,
              "attributes": None, "_viewport_box": None}])), \
         patch("app.core.storage.storage_client.upload_bytes", new=AsyncMock(return_value="http://minio/s.png")), \
         patch("app.api.v1.elements.CaptureSessionService") as mock_svc, \
         patch("app.api.v1.elements.SSEStream") as mock_sse_cls:
        mock_svc.create = AsyncMock(return_value={"session_id": "cap_x"})
        mock_svc.add_batch = AsyncMock(return_value={
            "batch_idx": 0, "batch_count": 1, "added": 1, "total_elements": 1})
        mock_sse = mock_sse_cls.return_value
        mock_sse.send_message = AsyncMock()
        r = client.post(f"/api/v1/elements/capture/browser/{SID}/capture")
    assert r.status_code == 200
    types = [(c.kwargs.get("type"), c.kwargs.get("progress")) for c in mock_sse.send_message.await_args_list]
    # 首条开始消息 + on_progress 计数消息 + success(1.0)
    assert types[0][0] == "system"
    assert ("success", 1.0) in types
    # 计数消息含元素数
    contents = [c.kwargs.get("content") for c in mock_sse.send_message.await_args_list]
    assert any("2 个元素" in c for c in contents)
```

（注意：现有 capture 测试若因新 SSEStream import 失败——capture 端点引用 SSEStream 后，未 patch 的测试会在模块层 import 报错吗？不会，SSEStream 只在端点体内实例化；但未 patch SSEStream 的既有测试会真连 Redis——**必须在实现时让 SSE 消息发送失败不影响端点**：用 try/except 包裹 SSEStream 实例化与发送（redis 不可用时静默跳过），这样既有测试（未 patch SSEStream 但 redis mock 环境）不受影响。若既有测试跑挂，再 patch。）

- [ ] **Step 2: 跑红 → Step 3: 实现**

elements.py capture_browser_page 端点体（`sess = _browser_sess_or_404(sid)` 之后）加：

```python
    # SSE 直播（进程内写 Redis List，复用 /api/sse/element-fetch/{sid} 订阅通道）；
    # 失败不影响抓取主流程
    try:
        from app.core.sse import SSEStream
        sse = SSEStream(sid)
    except Exception:
        sse = None
```

扫描前发开始消息；`scan_interactive_elements` 调用加 on_progress 回调：

```python
    TOTAL_ROUNDS_HINT = 12  # 选择器轮数估算（INTERACTIVE 10 + TEXT 9 + div 2，实际按序号线性推进）

    async def _scan_progress(selector, total):
        if sse:
            try:
                await sse.send_message(
                    type="system", stage="scan",
                    content=f"已扫描 {selector}，累计发现 {total} 个元素",
                    progress=min(0.7, 0.1 + total * 0.01))
            except Exception:
                pass

    if sse:
        try:
            await sse.send_message(type="system", stage="scan",
                                   content="正在扫描页面元素...", progress=0.05)
        except Exception:
            pass

    raw_elements = await _bridge.run(scan_interactive_elements(
        page, include_text=True, include_div_text=include_div_text,
        on_progress=_scan_progress))
```

过滤后、截图后、完成前分别发：

```python
    if sse:
        try:
            await sse.send_message(type="system", stage="filter",
                                   content=f"过滤后保留 {len(elements)} 个元素", progress=0.8)
        except Exception:
            pass
```

```python
    if sse:
        try:
            await sse.send_message(type="system", stage="staging",
                                   content="正在写入暂存列表...", progress=0.9)
        except Exception:
            pass
```

（在 `result = await CaptureSessionService.add_batch(...)` 之后、return 之前）：

```python
    if sse:
        try:
            await sse.send_message(
                type="success", stage="done",
                content=f"抓取完成：本批 {len(elements)} 个元素", progress=1.0,
                data={"total_count": len(elements), "batch_idx": result["batch_idx"],
                      "batch_count": result["batch_count"], "staging_session_id": staging_id})
        except Exception:
            pass
```

端点现有外层 try/except（如有异常路径）补 error 消息——查现有端点无 try/except（异常直接冒泡给全局 handler），在端点开头包一层：

```python
    try:
        ...现有主体...
    except HTTPException:
        raise
    except Exception as e:
        if sse:
            try:
                await sse.send_message(type="error", stage="error",
                                       content=f"抓取失败: {str(e)[:200]}", progress=0)
            except Exception:
                pass
        raise
```

- [ ] **Step 4: 绿 + 回归 → Commit**

`python -m pytest tests/test_api_capture_session.py -q` 全 PASS（若既有 capture 测试因真 SSEStream 连不上 redis 报错，给它们加 SSEStream patch 或确认 redis 桩已兜底）；`python -m pytest -q` 全 PASS

```bash
git add backend/app/api/v1/elements.py backend/tests/test_api_capture_session.py
git commit -m "feat(elements): 会话抓取端点发SSE直播消息(开始/按轮计数/完成error路径)"
```

---

### Task 3: 前端工作台直播面板

**Files:**
- Modify: `frontend/src/components/element/CaptureWorkbench.vue`
- Verify: `cd /d/MoonTest/frontend && npm run build`

- [ ] **Step 1: 模板加直播面板**

左栏 el-card 内、`.shot-container` 之后（pick-hint div 之前）加：

```html
            <div v-if="liveMessages.length" class="live-feed">
              <el-alert title="抓取进度直播" type="info" :closable="false" style="margin-top: 10px">
                <div v-for="(msg, i) in liveMessages" :key="i" class="live-message" :class="{ 'is-error': msg.type === 'error' }">
                  <span class="live-time">{{ msg.timestamp }}</span>
                  <span class="live-text">{{ msg.content }}</span>
                </div>
              </el-alert>
            </div>
```

- [ ] **Step 2: script**

2a) 状态（staging 列表区附近）：

```javascript
// SSE 直播（对齐一次性抓取体验：消息流 + 计数）
const liveMessages = ref([])
let sseConnection = null
const closeSse = () => { if (sseConnection) { sseConnection.close(); sseConnection = null } }
```

2b) `captureNow` 改造：

```javascript
const captureNow = async () => {
  capturing.value = true
  liveMessages.value = []
  closeSse()
  // 订阅直播通道（与一次性抓取共用 /api/sse/element-fetch；EventSource 不走 axios baseURL）
  sseConnection = new EventSource(`/api/sse/element-fetch/${browserSessionId.value}`)
  sseConnection.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      liveMessages.value.push({
        timestamp: new Date(data.timestamp).toLocaleTimeString('zh-CN'),
        content: data.content,
        type: data.type
      })
    } catch { /* 忽略解析失败 */ }
  }
  try {
    const r = await elementAPI.captureBrowserPage(browserSessionId.value, {
      exclude_menu: !pickMenu.value,
      max_list_rows: listRows.value || undefined,
      include_div_text: pickText.value
    })
    stagingSessionId.value = r.staging_session_id
    await refreshStaging()
    ElMessage.success(`批次 ${r.batch_idx + 1} 抓取完成：+${r.total_count} 元素`)
    refreshScreenshot()
  } catch (err) {
    ElMessage.error('抓取失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    capturing.value = false
    closeSse()
  }
}
```

2c) `closeSessionInternal` 加 `closeSse()`；`onUnmounted` 处已有 `stopPolling`，改为 `onUnmounted(() => { stopPolling(); closeSse() })`。

- [ ] **Step 3: 样式（对齐 ElementLibrary 的 live-feed）**

```css
.live-feed .live-message {
  display: flex;
  gap: 8px;
  font-size: 12px;
  line-height: 20px;
}
.live-feed .live-time {
  color: var(--mt-text-secondary, #909399);
  flex-shrink: 0;
}
.live-feed .live-message.is-error .live-text {
  color: var(--el-color-danger);
}
```

- [ ] **Step 4: build → Commit**

```bash
git add frontend/src/components/element/CaptureWorkbench.vue
git commit -m "feat(elements): 会话抓取SSE直播面板(消息流+计数,复用element-fetch通道)"
```

---

### Task 4: 全量回归 + 验收清单

- [ ] `python -m pytest -q` 全 PASS；`npm run build` 成功
- [ ] 输出验收清单（序号/原始描述/原因/修改方案/涉及功能点）
