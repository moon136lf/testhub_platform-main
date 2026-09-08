# 点选补抓增强：DOM 路径面包屑 + 悬停高亮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 点选补抓命中后显示完整 DOM 路径面包屑（每级可点 → 页面高亮 + 定位卡片切换），同级兄弟列表可切换目标。

**Spec:** `docs/superpowers/specs/2026-09-08-pick-breadcrumb-design.md`

**已有资产:** bs_* 会话（browser_session_manager + _bridge）、`_PICK_MARKER_JS`/`PICK_HIT_SELECTOR`（playwright_locator_core.py:326-334）、`generate_locators_for_element`/`verify_and_score_locator`/`extract_semantic_info` 流水线、CaptureWorkbench 点选卡片。

---

### Task 1: 后端 — css_path 生成 + 3 个端点

**Files:**
- Modify: `backend/app/services/playwright_locator_core.py`（提取 build_css_path + node-info JS 常量）
- Modify: `backend/app/api/v1/elements.py`（3 端点）
- Modify: `backend/app/schemas/element_schema.py`（请求/响应模型）
- Test: `backend/tests/test_api_capture_session.py`（追加）

- [ ] Step 1: 失败测试（追加到 test_api_capture_session.py）

```python
class TestNodeBreadcrumb:
    def test_node_info_returns_chain(self, client):
        """node-info: 打标记并返回祖先链（每层含 tag/css_path）。"""
        # mock browser_mgr.get_page → mock page（evaluate 返回预设 chain）
        # POST /elements/capture/browser/{sid}/node-info {x: 100, y: 200}
        # assert 200, data.chain 非空, data.chain[-1]["css_path"] 含 "html"
    def test_node_highlight_found_and_missing(self, client):
        """node-highlight: css_path 查询命中 found=true; 未命中 found=false 不抛错。"""
    def test_node_locators_regenerates(self, client):
        """node-locators: 对 css_path 节点重跑流水线, 返回 pick-element 同构 element。"""
    def test_marker_cleared_on_next_pick(self, client):
        """下次 pick-node-info 前清除旧标记（会话级标记生命周期）。"""
```

（mock 模式参照文件内既有 TestPickElement——browser_mgr patched at `app.api.v1.elements`，page.evaluate AsyncMock 按调用序返回。）

- [ ] Step 2: 确认失败

- [ ] Step 3: 实现

**playwright_locator_core.py** 追加（与 PICK_HIT_SELECTOR 同区）：

```python
_BUILD_CSS_PATH_JS = """
(el) => {
  let path = [];
  let cur = el;
  let depth = 0;
  while (cur && cur.tagName && depth < 8) {
    let seg = cur.tagName.toLowerCase();
    if (cur.id) { path.unshift(seg + '#' + cur.id); break; }
    const parent = cur.parentElement;
    if (parent) {
      const same = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
      if (same.length > 1) seg += `:nth-of-type(${same.indexOf(cur) + 1})`;
    }
    path.unshift(seg);
    cur = parent;
    depth++;
  }
  return path.join(' > ');
}
"""

_ANCESTOR_CHAIN_JS = """
(el) => {
  const chain = [];
  let cur = el;
  let depth = 0;
  while (cur && cur.tagName && depth < 8) {
    const seg = cur.tagName.toLowerCase();
    const parent = cur.parentElement;
    let css = seg;
    if (parent) {
      const same = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
      if (same.length > 1) css += `:nth-of-type(${same.indexOf(cur) + 1})`;
    }
    chain.push({
      tag: seg,
      id: cur.id || null,
      cls: (cur.className || '').toString().slice(0, 60) || null,
      text: (cur.innerText || '').trim().slice(0, 50) || null,
      css_path: chainCss(cur),  // 见下：逐层构建
      index_in_parent: parent ? Array.from(parent.children).indexOf(cur) : 0,
    });
    cur = parent;
    depth++;
  }
  return chain;
}
"""
```
（注：chainCss 逐层构建需在 JS 内实现——把 generate_locators 的 css path 循环内联进 chain 构建；实现时展开为完整 JS，别用伪码。）

**elements.py** 3 端点：

```python
@router.post("/capture/browser/{sid}/node-info")
async def node_info(sid: str, request: BrowserPickRequest):
    """点选坐标 → 打标记 → 返回祖先链（面包屑数据）。标记保留至下次 pick/会话关闭。"""
    page = browser_mgr.get_page(sid); 404 if None
    chain = await _bridge.run(page.evaluate(_NODE_CHAIN_JS, [request.x, request.y]))
    # evaluate 内: elementFromPoint → 打标记 → 沿 parentElement 上溯 8 层构建 chain（含每层 css_path）
    return {"code": 0, "data": {"chain": chain, "current_index": 0}}

@router.post("/capture/browser/{sid}/node-highlight")
async def node_highlight(sid: str, request: NodeHighlightRequest):
    """按 css_path 查节点 → 橙色闪烁 2 秒。"""
    page = browser_mgr.get_page(sid); 404 if None
    found = await _bridge.run(_call(page.evaluate,
        "(p) => { const el = document.querySelector(p); if (!el) return false;"
        " el.scrollIntoView({block:'center'});"
        " el.style.outline = '3px solid #e6a23c'; el.style.background = 'rgba(230,162,60,0.45)';"
        " setTimeout(() => { el.style.outline=''; el.style.background=''; }, 2000);"
        " return true; }", [request.css_path]))
    return {"code": 0, "data": {"found": bool(found)}}

@router.post("/capture/browser/{sid}/node-locators")
async def node_locators(sid: str, request: NodeHighlightRequest):
    """按 css_path 对节点重跑定位器流水线 → 返回定位卡片数据。"""
    page = browser_mgr.get_page(sid); 404 if None
    element = await _bridge.run(_node_locators_via_css(page, request.css_path))
    if element is None:
        raise HTTPException(status_code=404, detail="Node not found (page may have changed)")
    return {"code": 0, "data": {"element": element}}
```

`_node_locators_via_css`（playwright_locator_core.py）：
```python
async def _node_locators_via_css(page, css_path: str):
    locator = page.locator(css_path).first
    try:
        candidates = await generate_locators_for_element(page, locator)
        verified = [...]  # 与 _pick_element_via_dom 相同的 verify/score 循环
        semantic = await extract_semantic_info(page, locator)
    except Exception:
        return None
    # 组装与 _pick_element_via_dom 同构的 element dict
```
（extract _verify 循环与 _pick_element_via_dom 重复——提取共用 helper `_pipeline_for_locator(page, locator)`，两处调用。）

**标记生命周期**：node-info 的 evaluate 里先 `document.querySelectorAll('[data-pick-hit]').forEach(e => e.removeAttribute('data-pick-hit'))` 再打新标记。

- [ ] Step 4: 测试绿 + 全量不回归
- [ ] Step 5: Commit `feat(elements): node breadcrumb endpoints — chain/highlight/locators (#elem-bc T1)`

---

### Task 2: 前端 — 面包屑卡片 + 同级切换

**Files:**
- Modify: `frontend/src/api/element.js`（+3 方法，解包 response.data.data）
- Modify: `frontend/src/components/element/CaptureWorkbench.vue`（定位卡片增强）

- [ ] Step 1: element.js 方法

```js
async getNodeInfo(sessionId, x, y) { ... POST .../node-info }        // → {chain, current_index}
async highlightNode(sessionId, cssPath) { ... POST .../node-highlight } // → {found}
async getNodeLocators(sessionId, cssPath) { ... POST .../node-locators } // → element dict
```

- [ ] Step 2: CaptureWorkbench 点选流改造

现流程：onShotClick → pickBrowserElement → pickCard 展示。
新流程：
1. `onShotClick` → `getNodeInfo(sid, x, y)`（替代 pickBrowserElement 首调）→ 保存 `chain`、`currentIdx = chain.length - 1`（默认选中命中元素）
2. 卡片模板追加：
   - 面包屑行：`v-for="(c, i) in chain"`，每级 `<span class="crumb" @click="switchLevel(i)">`，当前级高亮，级间 `▸`
   - 同级列表：`siblings`（切层级时由后端 chain 提供——见下）每项可点
   - [加入当前页] 按当前选中层的 element 数据走原 staging add 流程
3. `switchLevel(i)`：
   - `highlightNode(sid, chain[i].css_path)` → found=false 时 ElMessage「页面已变化，请重新点选」并回退
   - `getNodeLocators(sid, chain[i].css_path)` → 更新 pickCard（类型/文本/策略/坐标）
   - currentIdx = i
4. 同级列表：node-info 的 chain 只含祖先——**同级需另取**。方案：switchLevel 时 node-locators 响应里附带 `parent_css_path`，前端再用一次 node-info 式 evaluate 拿同父 children？**简化决策**：node-locators 响应直接附 `siblings: [{tag, text, css_path}]`（后端 evaluate 同父 children 一次取齐），前端零额外请求。

- [ ] Step 3: vite build 绿
- [ ] Step 4: Commit `feat(elements): breadcrumb card with sibling switching (#elem-bc T2)`

---

### Task 3: 端到端验证

- [ ] 后端全量 + build
- [ ] 真实验收（用户）：会话抓取 → 点选 → 面包屑出现 → 点父级（页面闪烁+卡片切换）→ 同级切换 → 加入当前页 → staging 有该元素
- [ ] Commit fixup if any

---

## 注意
- 后端 node 相关端点全部经 `_bridge.run`（Playwright 对象绑定 bridge loop，跨 loop 直接调用会炸——P3 教训）
- 测试 mock page.evaluate 时注意调用序（一次端点可能多次 evaluate）
- 另一会话工作已全部提交，工作区干净；不要碰 sse.py 等非元素库文件
