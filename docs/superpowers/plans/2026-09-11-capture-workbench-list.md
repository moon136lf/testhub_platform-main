# 会话式抓取列表补齐 + 文本抓取范围扩展 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 会话式抓取工作台补齐悬浮高亮/框选标注/别名编辑/策略展示/一键入库计数，并新增「抓展示文本」扫描（div 叶子 + 无 href 的 a，修面包屑「首页」抓不到）。

**Architecture:** 后端：`scan_interactive_elements` 加 `include_div_text` 参数新增一轮扫描（复用 seen_coords 去重）；`CaptureSessionService.rename_element` 写 Redis staging 的 `element_name`；两个端点透传。前端：CaptureWorkbench 左栏换 ElementHighlight 组件（pickMode 时 pointer-events:none），列表行加内联别名输入 + 策略 popover，FetchDialog/CaptureWorkbench 加「抓展示文本」开关。

**Tech Stack:** FastAPI + Redis (fakeredis 桩测试) / Vue3 + Element Plus / pytest (790 基线)

**Spec:** `docs/superpowers/specs/2026-09-10-capture-workbench-list-design.md`

**测试基线:** `cd backend && python -m pytest -x -q` → 790 passed。前端验证：`cd frontend && npm run build`。

---

### Task 1: 扫描器 include_div_text（div 叶子 + 无 href a）

**Files:**
- Modify: `backend/app/services/playwright_locator_core.py:328-376`（scan_interactive_elements）
- Test: `backend/tests/test_element_scanning.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_element_scanning.py` 的 `TestScanInteractiveElements` 类末尾追加：

```python
    @staticmethod
    def _text_locator_factory(selector, elem, text="首页"):
        def locator_factory(sel):
            mock_loc = AsyncMock()
            if sel == selector:
                if text is not None:
                    elem.inner_text = AsyncMock(return_value=text)
                mock_loc.all = AsyncMock(return_value=[elem])
            else:
                mock_loc.all = AsyncMock(return_value=[])
            return mock_loc
        return locator_factory

    @pytest.mark.asyncio
    async def test_div_text_captures_leaf_div(self):
        """include_div_text=True 时抓叶子 div"""
        from unittest.mock import patch
        elem = _make_elem(visible=True, box={"x": 100, "y": 50, "width": 60, "height": 20})
        # evaluate("el => el.children.length") 返回 0 = 叶子
        elem.evaluate = AsyncMock(return_value=0)
        page = AsyncMock()
        page.locator = MagicMock(side_effect=self._text_locator_factory("div", elem))
        with patch("app.services.playwright_locator_core.INTERACTIVE_SELECTORS", []), \
             patch("app.services.playwright_locator_core.TEXT_SELECTORS", []):
            result = await scan_interactive_elements(page, include_text=True, include_div_text=True)
        assert len(result) == 1
        assert result[0] is elem

    @pytest.mark.asyncio
    async def test_div_text_skips_non_leaf_div(self):
        """非叶子 div（有子元素）不抓"""
        from unittest.mock import patch
        elem = _make_elem(visible=True, box={"x": 100, "y": 50, "width": 60, "height": 20})
        elem.evaluate = AsyncMock(return_value=3)  # 有子元素
        page = AsyncMock()
        page.locator = MagicMock(side_effect=self._text_locator_factory("div", elem))
        with patch("app.services.playwright_locator_core.INTERACTIVE_SELECTORS", []), \
             patch("app.services.playwright_locator_core.TEXT_SELECTORS", []):
            result = await scan_interactive_elements(page, include_text=True, include_div_text=True)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_div_text_off_by_default(self):
        """include_div_text 缺省（False）不抓 div 叶子"""
        from unittest.mock import patch
        page = AsyncMock()
        page.locator = MagicMock(side_effect=self._text_locator_factory("div", _make_elem()))
        with patch("app.services.playwright_locator_core.INTERACTIVE_SELECTORS", []), \
             patch("app.services.playwright_locator_core.TEXT_SELECTORS", []):
            result = await scan_interactive_elements(page, include_text=True)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_a_without_href_captured_in_div_round(self):
        """无 href 的 a（面包屑首页）在 div 轮被抓到"""
        from unittest.mock import patch
        elem = _make_elem(visible=True, box={"x": 100, "y": 50, "width": 60, "height": 20})
        elem.evaluate = AsyncMock(return_value=0)
        page = AsyncMock()
        page.locator = MagicMock(side_effect=self._text_locator_factory("a:not([href])", elem))
        with patch("app.services.playwright_locator_core.INTERACTIVE_SELECTORS", []), \
             patch("app.services.playwright_locator_core.TEXT_SELECTORS", []):
            result = await scan_interactive_elements(page, include_text=True, include_div_text=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_div_text_dedupes_with_seen_coords(self):
        """div 轮与已有元素同坐标时不重复（seen_coords 复用）"""
        from unittest.mock import patch
        span_elem = _make_elem(visible=True, box={"x": 10, "y": 20, "width": 80, "height": 30})
        span_elem.inner_text = AsyncMock(return_value="统计")
        div_elem = _make_elem(visible=True, box={"x": 10, "y": 20, "width": 80, "height": 30})
        div_elem.evaluate = AsyncMock(return_value=0)
        div_elem.inner_text = AsyncMock(return_value="统计")

        def locator_factory(selector):
            mock_loc = AsyncMock()
            if selector == "span":
                mock_loc.all = AsyncMock(return_value=[span_elem])
            elif selector == "div":
                mock_loc.all = AsyncMock(return_value=[div_elem])
            else:
                mock_loc.all = AsyncMock(return_value=[])
            return mock_loc

        page = AsyncMock()
        page.locator = MagicMock(side_effect=locator_factory)
        with patch("app.services.playwright_locator_core.INTERACTIVE_SELECTORS", []), \
             patch("app.services.playwright_locator_core.TEXT_SELECTORS", ["span"]):
            result = await scan_interactive_elements(page, include_text=True, include_div_text=True)
        assert len(result) == 1
        assert result[0] is span_elem

    @pytest.mark.asyncio
    async def test_div_text_skips_long_text(self):
        """inner_text 超 100 字的 div 叶子不抓"""
        from unittest.mock import patch
        elem = _make_elem(visible=True, box={"x": 100, "y": 50, "width": 60, "height": 20})
        elem.evaluate = AsyncMock(return_value=0)
        page = AsyncMock()
        page.locator = MagicMock(side_effect=self._text_locator_factory("div", elem, text="长" * 101))
        with patch("app.services.playwright_locator_core.INTERACTIVE_SELECTORS", []), \
             patch("app.services.playwright_locator_core.TEXT_SELECTORS", []):
            result = await scan_interactive_elements(page, include_text=True, include_div_text=True)
        assert len(result) == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_element_scanning.py -k div_text -x -q`
Expected: FAIL — `TypeError: scan_interactive_elements() got an unexpected keyword argument 'include_div_text'`

- [ ] **Step 3: 实现**

`backend/app/services/playwright_locator_core.py`：在 `TEXT_SELECTORS = [...]`（325 行）后加：

```python
# 「抓展示文本」扩展选择器：div 叶子节点（统计卡片等布局文本）+ 无 href 的 a（面包屑首页等）
DIV_TEXT_SELECTORS = ["div", "a:not([href])"]
```

`scan_interactive_elements` 签名改为：

```python
async def scan_interactive_elements(
    page, include_text: bool = False, include_div_text: bool = False
) -> List[Any]:
```

docstring Args 补一行：`include_div_text: 扫描 div 叶子节点与无 href 链接（展示文本，需 include_text=True 才生效）`

函数末尾（374 行 `await scan_selectors(TEXT_SELECTORS, require_text=True)` 之后）改为：

```python
    await scan_selectors(INTERACTIVE_SELECTORS, require_text=False)
    if include_text:
        await scan_selectors(TEXT_SELECTORS, require_text=True)
        if include_div_text:
            await scan_div_text_selectors()
```

在 `scan_selectors` 内嵌函数之后、调用之前新增内嵌函数：

```python
    async def scan_div_text_selectors():
        """div 叶子 + 无 href a：叶子判定用 children.length，文本非空 ≤100 字"""
        for selector in DIV_TEXT_SELECTORS:
            try:
                found = await page.locator(selector).all()
                for elem in found:
                    try:
                        if not await elem.is_visible():
                            continue
                        if int(await elem.evaluate("el => el.children.length")) != 0:
                            continue
                        raw = await elem.inner_text()
                        if not raw.strip() or len(raw.strip()) > 100:
                            continue
                        box = await elem.bounding_box()
                        if box:
                            coord_key = (int(box["x"]), int(box["y"]))
                            if coord_key in seen_coords:
                                continue
                            seen_coords.add(coord_key)
                        elements.append(elem)
                    except Exception:
                        continue
            except Exception:
                continue
```

注意：`a:not([href])` 不需要叶子判定也安全（`evaluate` 对 a 同样适用；有子节点的 a 会被 children.length 过滤——这正是嵌套 span 的 a，文本已由 span 轮覆盖）。但为保持 div/a 一致，都用 children.length 判定（测试 `test_a_without_href_captured_in_div_round` 的 elem.evaluate 返回 0 已兼容）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_element_scanning.py -q`
Expected: 全部 PASS（原有 6 个 + 新 6 个）

- [ ] **Step 5: 全量回归**

Run: `cd backend && python -m pytest -q`
Expected: 796 passed（790 + 6）

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/playwright_locator_core.py backend/tests/test_element_scanning.py
git commit -m "feat(elements): 扫描器加 include_div_text——div叶子+无href链接(面包屑盲区)"
```

---

### Task 2: 端点/Schema/任务透传 include_div_text（两处调用点）

**Files:**
- Modify: `backend/app/schemas/element_schema.py:98-100`（ElementFetchRequest 加字段）
- Modify: `backend/app/api/v1/elements.py:750-763`（capture/browser/{sid}/capture 加 query）+ `:139`（fetch 端点透传）+ `:100-110`（fetch_elements_task.delay 参数）
- Modify: `backend/app/tasks/element_tasks.py:80-111,123,170`（任务透传）
- Test: `backend/tests/test_api_capture_session.py`、`backend/tests/test_element_tasks.py`

- [ ] **Step 1: 写失败测试（会话抓取端点透传）**

在 `backend/tests/test_api_capture_session.py` 的 `test_capture_adds_to_staging`（144 行）之后追加。该文件已有 `_fake_page`、`mgr` fixture、TestClient。先看 144-168 行确认 mock 方式（patch `scan_interactive_elements` 与 `_verify_elements` 的方式保持一致）：

```python
def test_capture_passes_include_div_text(client, mgr):
    """capture 端点应把 include_div_text query 透传给 scan_interactive_elements"""
    with patch("app.api.v1.elements.scan_interactive_elements", new=AsyncMock(return_value=[])) as mock_scan, \
         patch("app.api.v1.elements._verify_elements", new=AsyncMock(return_value=[])), \
         patch("app.core.storage.storage_client.upload_bytes", new=AsyncMock(return_value="http://minio/s.png")), \
         patch("app.api.v1.elements.CaptureSessionService") as mock_svc:
        mock_svc.create = AsyncMock(return_value={"session_id": "cap_x"})
        mock_svc.add_batch = AsyncMock(return_value={
            "batch_idx": 0, "batch_count": 1, "added": 0, "total_elements": 0})
        r = client.post(
            f"/api/v1/elements/capture/browser/{SID}/capture?include_div_text=false")
    assert r.status_code == 200
    kwargs = mock_scan.call_args.kwargs
    assert kwargs["include_div_text"] is False

    with patch("app.api.v1.elements.scan_interactive_elements", new=AsyncMock(return_value=[])) as mock_scan2, \
         patch("app.api.v1.elements._verify_elements", new=AsyncMock(return_value=[])), \
         patch("app.core.storage.storage_client.upload_bytes", new=AsyncMock(return_value="http://minio/s.png")), \
         patch("app.api.v1.elements.CaptureSessionService") as mock_svc2:
        mock_svc2.create = AsyncMock(return_value={"session_id": "cap_x"})
        mock_svc2.add_batch = AsyncMock(return_value={
            "batch_idx": 0, "batch_count": 1, "added": 0, "total_elements": 0})
        client.post(f"/api/v1/elements/capture/browser/{SID}/capture")
    assert mock_scan2.call_args.kwargs["include_div_text"] is True  # 默认开
```

（若该文件现有测试对 scan 的 patch 路径/方式不同，以现有 `test_capture_adds_to_staging` 的写法为准，只保留 assert 透传的部分。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_api_capture_session.py::test_capture_passes_include_div_text -x -q`
Expected: FAIL — 端点无 `include_div_text` query，kwargs 里没有该键（或调用仍是位置参数 include_text=True）

- [ ] **Step 3: 实现 capture 端点 + ElementFetchRequest + 任务透传**

`backend/app/api/v1/elements.py:750-755` 端点签名加参数：

```python
@router.post("/capture/browser/{sid}/capture")
async def capture_browser_page(
    sid: str,
    exclude_menu: bool = Query(False, description="排除左侧菜单栏元素"),
    max_list_rows: Optional[int] = Query(None, ge=1, le=50, description="表格单元格只保留最上 N 行"),
    include_div_text: bool = Query(True, description="抓展示文本（div叶子+无href链接）"),
):
```

763 行调用改为：

```python
    raw_elements = await _bridge.run(scan_interactive_elements(
        page, include_text=True, include_div_text=include_div_text))
```

`backend/app/schemas/element_schema.py` ElementFetchRequest（98 行 include_text 之后）加：

```python
    include_div_text: bool = Field(True, description="抓展示文本（div叶子+无href链接，需 include_text）")
```

`backend/app/api/v1/elements.py:139` fetch 端点 `.delay(...)` 参数加 `include_div_text=request.include_div_text,`；`fetch_elements_task`（element_tasks.py:80）签名在 `include_text` 后加 `include_div_text: bool = True,`；`asyncio.run(_fetch_elements_async(...))` 调用（110 行）与 `_fetch_elements_async` 签名（123 行）同步加参；170 行调用改为：

```python
        raw_elements = await scan_interactive_elements(
            page, include_text=include_text, include_div_text=include_div_text)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_api_capture_session.py tests/test_element_tasks.py tests/test_api_elements.py -q`
Expected: 全 PASS（test_element_tasks 里 `fake_scan(page, include_text=False)` 若因新 kwargs 报错，把该 fake 签名改为 `async def fake_scan(page, include_text: bool = False, include_div_text: bool = True)`）

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/element_schema.py backend/app/api/v1/elements.py backend/app/tasks/element_tasks.py backend/tests/test_api_capture_session.py backend/tests/test_element_tasks.py
git commit -m "feat(elements): 会话抓取/一次性抓取端点透传 include_div_text(默认开)"
```

---

### Task 3: rename_element 服务方法 + 端点

**Files:**
- Modify: `backend/app/services/capture_session_service.py`（remove_batch 后加 rename_element）
- Modify: `backend/app/schemas/element_schema.py`（CaptureElementDeleteRequest 后加 CaptureRenameRequest）
- Modify: `backend/app/api/v1/elements.py:543` 附近（加 rename 端点）
- Test: `backend/tests/test_capture_session_service.py`、`backend/tests/test_api_capture_session.py`

- [ ] **Step 1: 写失败测试（服务层）**

在 `backend/tests/test_capture_session_service.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_rename_element(patch_redis):
    s = await CaptureSessionService.create("p")
    sid = s["session_id"]
    await CaptureSessionService.add_batch(sid, "u", "", [
        {"temp_id": "t1", "element_type": "link", "element_text": "首页",
         "locator_strategies": {"strategies": []}, "semantic_info": {}}])
    # 正常改名
    assert await CaptureSessionService.rename_element(sid, "t1", "面包屑首页") is True
    state = await CaptureSessionService.get(sid)
    assert state["elements"]["t1"]["element_name"] == "面包屑首页"
    # 元素不存在 → False
    assert await CaptureSessionService.rename_element(sid, "nope", "x") is False
    # 会话不存在 → False
    assert await CaptureSessionService.rename_element("cap_missing", "t1", "x") is False


@pytest.mark.asyncio
async def test_rename_element_truncates_to_100(patch_redis):
    s = await CaptureSessionService.create("p")
    sid = s["session_id"]
    await CaptureSessionService.add_batch(sid, "u", "", [
        {"temp_id": "t1", "element_type": "button", "element_text": "",
         "locator_strategies": {"strategies": []}, "semantic_info": {}}])
    await CaptureSessionService.rename_element(sid, "t1", "长" * 150)
    state = await CaptureSessionService.get(sid)
    assert len(state["elements"]["t1"]["element_name"]) == 100
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_capture_session_service.py -k rename -x -q`
Expected: FAIL — `AttributeError: ... has no attribute 'rename_element'`

- [ ] **Step 3: 实现服务方法**

`backend/app/services/capture_session_service.py` 在 `remove_batch` 方法后追加：

```python
    @staticmethod
    async def rename_element(session_id: str, temp_id: str, element_name: str) -> bool:
        """改元素别名（写 element_name，截断 100 字；入库时走 batch_import 的 user_name 分支）"""
        state = await CaptureSessionService._load(session_id)
        if state is None or temp_id not in state["elements"]:
            return False
        state["elements"][temp_id]["element_name"] = (element_name or "").strip()[:100]
        await CaptureSessionService._save(session_id, state)
        return True
```

- [ ] **Step 4: 服务测试通过**

Run: `cd backend && python -m pytest tests/test_capture_session_service.py -q`
Expected: 全 PASS

- [ ] **Step 5: 写失败测试（API 端点）**

`backend/tests/test_api_capture_session.py` 现有会话端点测试（included/included-all/delete）如何拿 fakeredis —— 先看该文件或 `test_element_p3w_t4.py` 中会话端点测试的 redis patch 方式（grep `capture_session_service.redis_client` / `patch_redis`）。按同一模式追加（以下假设与既有端点测试相同的 patch 方式，若既有模式是 patch `app.api.v1.elements.CaptureSessionService` 则照抄该模式改写）：

```python
def test_rename_endpoint(client):
    """rename 端点：成功 / 元素不存在 404"""
    from unittest.mock import patch as _patch, AsyncMock as _AsyncMock
    with _patch("app.api.v1.elements.CaptureSessionService") as mock_svc:
        mock_svc.rename_element = _AsyncMock(return_value=True)
        r = client.post("/api/v1/elements/capture/sessions/cap_x/elements/rename",
                        json={"temp_id": "t1", "element_name": "登录按钮"})
        assert r.status_code == 200
        assert r.json() == {"temp_id": "t1", "element_name": "登录按钮"}

        mock_svc.rename_element = _AsyncMock(return_value=False)
        r = client.post("/api/v1/elements/capture/sessions/cap_x/elements/rename",
                        json={"temp_id": "nope", "element_name": "x"})
        assert r.status_code == 404
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_api_capture_session.py::test_rename_endpoint -x -q`
Expected: FAIL — 404 route not found（TestClient 对无路由返回 404，断言第一个请求 status 200 失败）

- [ ] **Step 7: 实现端点**

`backend/app/schemas/element_schema.py` 在 `CaptureElementDeleteRequest`（259 行）后加：

```python
class CaptureRenameRequest(BaseModel):
    """元素别名重命名（会话式抓取列表内联编辑）"""

    temp_id: str = Field(..., description="元素临时 ID")
    element_name: str = Field(..., min_length=1, max_length=200, description="新别名（服务端截断 100 字）")
```

`backend/app/api/v1/elements.py` 在 `delete_capture_element` 端点（547 行 `return {"deleted": ...}` 之后）加：

```python
@router.post("/capture/sessions/{session_id}/elements/rename")
async def rename_capture_element(session_id: str, request: CaptureRenameRequest):
    if not await CaptureSessionService.rename_element(
        session_id, request.temp_id, request.element_name
    ):
        raise HTTPException(status_code=404, detail="Element not found in session")
    return {"temp_id": request.temp_id, "element_name": request.element_name}
```

（import 处确认 `CaptureRenameRequest` 已在 element_schema 的 import 列表中。）

- [ ] **Step 8: 跑测试确认通过 + 回归**

Run: `cd backend && python -m pytest tests/test_api_capture_session.py -q && python -m pytest -q`
Expected: 全 PASS（基线 + 8）

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/capture_session_service.py backend/app/schemas/element_schema.py backend/app/api/v1/elements.py backend/tests/test_capture_session_service.py backend/tests/test_api_capture_session.py
git commit -m "feat(elements): 会话抓取元素改名端点 rename_element(写staging element_name)"
```

---

### Task 4: 前端 API + CaptureWorkbench 列表行重构（别名/策略/一键入库）+ 左栏 ElementHighlight + 开关

**Files:**
- Modify: `frontend/src/api/element.js`（captureBrowserPage 加参数、加 renameCaptureElement）
- Modify: `frontend/src/components/element/CaptureWorkbench.vue`
- Test: `cd frontend && npm run build`（无单测基建；行为靠真浏览器验收）

- [ ] **Step 1: element.js 加 API**

`captureBrowserPage`（176 行）params 加 `include_div_text: opts.include_div_text !== false`：

```javascript
  async captureBrowserPage(sessionId, opts = {}) {
    const response = await axios.post(`/elements/capture/browser/${sessionId}/capture`, null, {
      params: {
        exclude_menu: opts.exclude_menu || false,
        max_list_rows: opts.max_list_rows || undefined,
        include_div_text: opts.include_div_text !== false
      }
    })
    return response.data.data
  },
```

在 `deleteCaptureElement`（289 行）之后加：

```javascript
  /** 会话式抓取：元素别名内联改名 */
  async renameCaptureElement(sessionId, tempId, elementName) {
    const response = await axios.post(
      `/elements/capture/sessions/${sessionId}/elements/rename`,
      { temp_id: tempId, element_name: elementName }
    )
    return response.data
  },
```

- [ ] **Step 2: CaptureWorkbench 模板改造**

2a) 左栏截图区（89-92 行）替换为 ElementHighlight + pickMode 包裹：

```html
            <div class="shot-container" :class="{ picking: pickMode && !browserReleased }" @click="onShotClick">
              <ElementHighlight
                v-if="screenshotSrc && !pickMode"
                :screenshot-url="screenshotSrc"
                :elements="stagingState?.elements || []"
                :selected-ids="selectedIds"
                :hover-id="hoverId"
                @pick="onHotspotPick"
                @card-hover="onHotspotHover"
              />
              <img v-else-if="screenshotSrc" :src="screenshotSrc" class="shot-img" referrerpolicy="no-referrer" />
              <div v-else class="no-screenshot">{{ browserReleased ? '浏览器已释放' : '暂无截图，点击「刷新截图」' }}</div>
            </div>
```

pickMode 开启时用裸 img（点选走原 onShotClick），非 pickMode 用 ElementHighlight（框交互）。这比 pointer-events 方案更简单可靠。

2b) shot-header-actions（73 行抓菜单栏开关旁）加开关：

```html
                  <el-switch v-model="pickText" size="small" active-text="抓展示文本" />
```

2c) 列表行（117-129 行）整体替换：

```html
              <div
                v-for="el in stagingState.elements"
                :key="el.temp_id"
                class="wb-element"
                :class="{ excluded: !el.included, 'wb-element-hover': hoverId === el.temp_id }"
                @mouseenter="hoverId = el.temp_id"
                @mouseleave="hoverId = ''"
              >
                <el-checkbox :model-value="el.included" @change="(v) => toggleElement(el.temp_id, v)">
                  <el-tag :type="typeColor(el.element_type)" size="small">{{ el.element_type }}</el-tag>
                </el-checkbox>
                <el-input
                  v-model="el._nameDraft"
                  size="small"
                  class="wb-el-name"
                  placeholder="别名"
                  @change="(v) => commitRename(el, v)"
                  @keyup.enter="(e) => e.target.blur()"
                />
                <el-popover trigger="hover" placement="left" :width="360">
                  <template #reference>
                    <el-button size="small" text type="primary">
                      {{ (el.locator_strategies?.strategies || []).length }} 策略
                    </el-button>
                  </template>
                  <div class="strategy-pop">
                    <div v-for="(s, i) in (el.locator_strategies?.strategies || [])" :key="i" class="strategy-line">
                      {{ s.type }}: <span class="strategy-value" :title="s.value">{{ s.value }}</span> (score {{ s.score }})
                    </div>
                  </div>
                </el-popover>
                <el-tag size="small" type="info" effect="plain">批次 {{ (el.batch_idx ?? 0) + 1 }}</el-tag>
                <el-button size="small" type="danger" text @click="removeElement(el.temp_id)">删除</el-button>
              </div>
```

2d) 入库按钮（145-147 行）文案改为：

```html
              <el-button type="primary" size="small" :loading="importing" @click="importSelected">
                一键入库 ({{ stagingState.included_count }})
              </el-button>
```

- [ ] **Step 3: CaptureWorkbench script 改造**

3a) import：

```javascript
import ElementHighlight from '@/components/element/ElementHighlight.vue'
```

3b) ready 状态区（275 行 staging 列表附近）加：

```javascript
const pickText = ref(true)   // 抓展示文本（div叶子+无href链接），默认开
const hoverId = ref('')
const selectedIds = computed(() =>
  (stagingState.value?.elements || []).filter((e) => e.included).map((e) => e.temp_id)
)
```

3c) `refreshStaging` 拉到数据后为每行填草稿别名（在 `stagingState.value = await ...` 之后）：

```javascript
  if (stagingState.value?.elements) {
    stagingState.value.elements.forEach((el) => {
      el._nameDraft = el.element_name || el.element_text || ''
    })
  }
```

3d) 抓取调用（415 行）加参数：

```javascript
    const r = await elementAPI.captureBrowserPage(browserSessionId.value, {
      exclude_menu: !pickMenu.value,
      max_list_rows: listRows.value || undefined,
      include_div_text: pickText.value
    })
```

3e) 别名提交 + 框交互方法（removeElement 之后加）：

```javascript
// 别名内联编辑：值变化才调 API，失败警告不阻塞列表
const commitRename = async (el, value) => {
  const name = (value || '').trim()
  const original = el.element_name || el.element_text || ''
  if (name === original.trim()) { el._nameDraft = original; return }
  try {
    await elementAPI.renameCaptureElement(stagingSessionId.value, el.temp_id, name)
    el.element_name = name
    el._nameDraft = name
  } catch {
    ElMessage.warning('别名保存失败（会话可能已过期）')
  }
}

// 截图框 → 列表行联动：点框滚动到对应行并短暂高亮
const onHotspotPick = (tempId) => {
  const row = document.querySelector(`[data-temp-id="${tempId}"]`)
  if (row) {
    row.scrollIntoView({ behavior: 'smooth', block: 'center' })
    row.classList.add('wb-row-flash')
    setTimeout(() => row.classList.remove('wb-row-flash'), 1200)
  }
}
const onHotspotHover = (tempId) => { hoverId.value = tempId || '' }
```

3f) 列表行加 `:data-temp-id`（Step 2c 的 `v-for` 行上）：

```html
                :data-temp-id="el.temp_id"
```

3g) `closeSessionInternal`（648 行 pickMode.value = false 附近）加重置 `pickText.value = true`。

- [ ] **Step 4: 样式追加（style scoped 末尾）**

```css
.wb-el-name {
  width: 130px;
  margin: 0 6px;
}
.wb-element .el-checkbox {
  margin-right: 0;
}
.wb-element-hover {
  background: var(--el-fill-color, #f0f2f5);
}
.wb-row-flash {
  animation: row-flash 0.6s ease 2;
}
@keyframes row-flash {
  50% { background: rgba(230, 162, 60, 0.35); }
}
.strategy-pop .strategy-line {
  font-size: 12px;
  line-height: 20px;
  display: flex;
  gap: 4px;
  align-items: baseline;
}
.strategy-pop .strategy-value {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

同时 `.wb-element` 行改为允许多控件排布（原 justify-content: space-between 保留即可）。

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功无错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/element.js frontend/src/components/element/CaptureWorkbench.vue
git commit -m "feat(elements): 会话抓取列表补齐——别名内联编辑/策略popover/ElementHighlight双向联动/抓展示文本开关"
```

---

### Task 5: FetchDialog 加「抓展示文本」开关（一次性抓取调用点）

**Files:**
- Modify: `frontend/src/components/element/FetchDialog.vue:43-46,102,177`

- [ ] **Step 1: 模板加开关**（「文字元素」form-item 之后，47 行前）

```html
      <el-form-item label="展示文本">
        <el-switch v-model="form.include_div_text" />
        <span class="hint-text">抓 div 叶子文本与无 href 链接（统计卡片、面包屑等），默认开</span>
      </el-form-item>
```

- [ ] **Step 2: form 与提交参数**

102 行 form 加 `include_div_text: true,`；177 行提交对象加 `include_div_text: form.include_div_text,`。

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/element/FetchDialog.vue
git commit -m "feat(elements): 一次性抓取弹窗加「抓展示文本」开关(默认开)"
```

---

### Task 6: 全量回归 + 验收准备

- [ ] **Step 1: 后端全量**

Run: `cd backend && python -m pytest -q`
Expected: 798 passed（790 + 6 扫描 + 2 rename 服务 + 端点透传 1 含在 capture 文件内，以实际为准；不许有 fail）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 已知边界核对（不改，验收时说明）**

- 会话截图是视口截图，元素坐标是文档坐标 → 超一屏元素的框会落出截图范围（spec 记录不改）
- canvas 图表（ECharts）内部元素原理性不可抓 → 记入 ACCEPTANCE_CHECKLIST 已知问题
- 入库确认弹窗不做（内联编辑已覆盖别名诉求）

- [ ] **Step 4: 提醒用户真浏览器验收**

验收清单（对 spec 验收表）：全选保留 / 一键入库 (N) / 列表行 hover → 截图框橘色闪烁 / 点框 → 列表行滚动定位 / 别名内联编辑入库生效 / 策略 popover / 「抓展示文本」开关（面包屑「首页」、统计卡片数字抓到）/ 点选补抓模式不受影响。
