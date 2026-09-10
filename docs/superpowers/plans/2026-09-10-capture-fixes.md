# 验收反馈修复：会话抓取项目切换 + 一次性抓取红框偏移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复问题1（会话式抓取无法切换项目——projectId 只读 computed）和问题3（一次性抓取红框偏移——视口坐标 vs 整页截图坐标系错配）。

**Architecture:** 问题1纯前端：CaptureWorkbench.vue 的 projectId 从 computed 改 ref + 切换时重置 url 预填。问题3纯后端：extract_semantic_info 改用 `getBoundingClientRect + scrollX/scrollY` 取文档坐标（与 full_page 截图对齐），前端 ElementHighlight.vue 缩放逻辑不动（naturalWidth 含 DPR 自然抵消）。

**Tech Stack:** Vue3 + Element Plus；Python + Playwright；pytest + vitest（前端无组件测试，手工验收）

---

## 背景（工程师必读）

- 一次性抓取链路：`backend/app/tasks/element_tasks.py` `fetch_elements_task` → `extract_semantic_info`（坐标）→ `page.screenshot(full_page=True)`（截图）→ 前端 `ElementLibrary.vue` 用 `ElementHighlight.vue` 在截图上画红框。**坐标是 bounding_box() 的视口坐标，截图是整页文档坐标图 → 元素在折叠下方时 y 错位**。
- 会话式抓取链路：`CaptureWorkbench.vue`（idle 表单选项目）→ `openBrowserSession({project_id})`。下拉 v-model 绑的是 `computed(() => props.defaultProjectId)`（无 setter）→ 切换静默失败。
- `extract_semantic_info` 的 coords 还有消费方：`change_detection_service.py`（签名匹配，用 x/y 相对值，文档坐标同样成立）、会话抓取 staging（仅存库展示，不画在视口截图上）→ 改文档坐标安全。
- 视口截图（会话抓取 status 接口）不消费 coords 画框（点选走 elementFromPoint），不受影响。

---

### Task 1: extract_semantic_info 改文档坐标（问题3）

**Files:**
- Modify: `backend/app/services/playwright_locator_core.py:252-259`
- Test: `backend/tests/test_playwright_service.py:252-263`（TestExtractSemanticInfo）
- Test: `backend/tests/test_element_tasks.py:285-303`（TestSemanticCoords）

- [ ] **Step 1: 更新失败测试（两处）**

`test_playwright_service.py` 的 `_make_element`（19-50行）需要让 evaluate 能返回 rect。在 `test_extracts_coords_from_bounding_box` 之前加新测试（保留旧断言语义但改为文档坐标）：

```python
    @pytest.mark.asyncio
    async def test_coords_are_document_coords(self):
        """coords 必须是文档坐标（rect+scroll），与 full_page 截图坐标系对齐（红框偏移根因）。"""
        element = _make_element(box={"x": 100, "y": 50, "width": 80, "height": 30})
        # rect 是视口坐标：y=50 是滚动后视口内位置；scrollY=150 → 文档 y=200
        async def eval_rect(script, *args):
            if "getBoundingClientRect" in script:
                return {"x": 100, "y": 50}
            raise AssertionError("unexpected evaluate: " + script[:60])
        element.evaluate = eval_rect
        page = MagicMock()

        info = await extract_semantic_info(page, element)

        assert info["coords"] == {"x": 100, "y": 200, "width": 80, "height": 30}
```

注意：`_make_element` 的 evaluate 现有分支按脚本内容路由（tagName/parent/siblings），新增 rect 分支后其余测试不受影响（它们不 mock getBoundingClientRect 脚本，会走原分支；但 rect 调用对它们会执行原 evaluate 逻辑返回非 dict → 实现里必须 try/except 兜底回退 bounding_box）。在 `_make_element` 的 evaluate 里补一个分支：

```python
        if "getBoundingClientRect" in s:
            return {"x": box["x"], "y": box["y"]}
```

（box 变量在闭包外取不到——直接返回 `{"x": 10, "y": 20}`，与默认 box 一致；`_make_element` 里 box 参数化时该 helper 的两个自定义 box 测试需同步。最小方案：`_make_element` 内定义 `async def evaluate(script, *args)` 开头加：
```python
        if "getBoundingClientRect" in s:
            b = box or {"x": 10, "y": 20, "width": 80, "height": 30}
            return {"x": b["x"], "y": b["y"]}
```
box 在函数签名参数里，闭包可见。）

`test_element_tasks.py:287` 的 `test_semantic_coords_are_bounding_box` 重写（改名+改断言）：

```python
    @pytest.mark.asyncio
    async def test_semantic_coords_are_document_coords(self):
        """coords 必须是文档坐标 (rect+scroll)，与 full_page 截图对齐；rect 失败回退 bounding_box."""
        from unittest.mock import AsyncMock, MagicMock
        from app.services.playwright_locator_core import extract_semantic_info

        elem = MagicMock()
        elem.evaluate = AsyncMock(return_value="button")  # tagName + parent/sibling 共用返回桩
        elem.inner_text = AsyncMock(return_value="text")
        elem.get_attribute = AsyncMock(return_value=None)
        elem.bounding_box = AsyncMock(
            return_value={"x": 10, "y": 20, "width": 30, "height": 40}
        )

        info = await extract_semantic_info(MagicMock(), elem)

        # mock 的 evaluate 对 rect 脚本返回 "button"（非 dict）→ 回退 bounding_box
        elem.bounding_box.assert_awaited_once()
        assert info["coords"] == {"x": 10, "y": 20, "width": 30, "height": 40}
```

- [ ] **Step 2: 跑测试确认红**

Run: `cd backend && python -m pytest tests/test_playwright_service.py::TestExtractSemanticInfo tests/test_element_tasks.py::TestSemanticCoords -q`
Expected: `test_coords_are_document_coords` FAIL（coords.y==50 而非 200）

- [ ] **Step 3: 实现**

`backend/app/services/playwright_locator_core.py` 的 `extract_semantic_info`，将 252-259 行替换：

```python
    # 文档坐标（rect + scroll），与 full_page 截图坐标系对齐——一次性抓取红框
    # 偏移的根因是 bounding_box() 视口坐标对不上整页截图。rect 取不到时回退
    # bounding_box（视口坐标，页面未滚动时二者等价）。
    try:
        rect = await element.evaluate(
            "el => { const r = el.getBoundingClientRect(); "
            "return {x: r.x + window.scrollX, y: r.y + window.scrollY}; }"
        )
        box = await element.bounding_box()
        coords = {
            "x": int(rect["x"]) if rect else (int(box["x"]) if box else 0),
            "y": int(rect["y"]) if rect else (int(box["y"]) if box else 0),
            "width": int(box["width"]) if box else 0,
            "height": int(box["height"]) if box else 0,
        }
    except Exception:
        box = await element.bounding_box()
        coords = {
            "x": int(box["x"]) if box else 0,
            "y": int(box["y"]) if box else 0,
            "width": int(box["width"]) if box else 0,
            "height": int(box["height"]) if box else 0,
        }
```

- [ ] **Step 4: 跑测试确认绿 + 全量回归**

Run: `cd backend && python -m pytest tests/test_playwright_service.py tests/test_element_tasks.py -q` → PASS
Run: `cd backend && python -m pytest tests/ -q` → 790 passed（789+新增1）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/playwright_locator_core.py backend/tests/test_playwright_service.py backend/tests/test_element_tasks.py
git commit -m "fix(elements): 一次性抓取坐标改文档坐标对齐full_page截图(红框偏移)"
```

---

### Task 2: 会话抓取项目可切换（问题1）

**Files:**
- Modify: `frontend/src/components/element/CaptureWorkbench.vue:237-248`

前端无组件测试，跑 `npm run build` 验证 + 用户手工验收。

- [ ] **Step 1: 改 projectId 为可写 ref**

248 行 `const projectId = computed(() => props.defaultProjectId)` 改为：

```js
const projectId = ref(props.defaultProjectId)
// 项目切换（仅 idle 阶段下拉可见）：换项目后清空 URL 再按新项目预填系统地址
watch(projectId, (pid) => {
  if (phase.value !== 'idle') { projectId.value = props.defaultProjectId; return }
  url.value = ''
  const p = props.projects.find((x) => x.id === pid)
  if (p?.target_url) url.value = p.target_url
})
```

同时 238-246 行现有 `watch(() => props.defaultProjectId, ...)` 改为同步 ref（父组件初始加载是异步的，projects 到位后 defaultProjectId 才有值）：

```js
watch(
  () => props.defaultProjectId,
  (pid) => {
    if (!pid) return
    projectId.value = pid
    if (!url.value) {
      const p = props.projects.find((x) => x.id === pid)
      if (p?.target_url) url.value = p.target_url
    }
  },
  { immediate: true }
)
```

- [ ] **Step 2: build 验证**

Run: `cd frontend && npm run build`
Expected: 构建成功无报错

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/element/CaptureWorkbench.vue
git commit -m "fix(elements): 会话式抓取项目下拉可切换(projectId只读computed根因)"
```

---

### Task 3: 全量验证 + 交用户验收

- [ ] 后端全量 `python -m pytest tests/ -q` → 全绿
- [ ] 前端 `npm run build` → 成功
- [ ] 用户手工验收：①会话抓取切换项目重新开始 ②一次性抓取长页面（超过一屏）红框对齐
