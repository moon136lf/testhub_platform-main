# 元素管理批量修复（问题2-12）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复元素管理验收反馈 11 项（问题2-12）：会话高亮视口坐标、页面树层级+排序、新建带定位器、抽屉合并+刷新、调序、verify 桥接、树计数实时、回收站列+倒序、导出路径。

**Architecture:** 后端 5 个小改（排序/实时计数/回收站/verify桥接/视口坐标）+ 前端 2 个文件（ElementList.vue 大改、element.js 路径+参数）。TDD 后端、build 验证前端。

**Tech Stack:** FastAPI + SQLAlchemy async / Vue3 + Element Plus / pytest（基线 800）

**Spec:** `docs/superpowers/specs/2026-09-11-element-mgmt-fixes-design.md`

**测试基线:** `cd /d/MoonTest/backend && python -m pytest -q` → 800 passed。前端：`cd /d/MoonTest/frontend && npm run build`。

---

### Task 1: 后端——页面排序 sort_order + 树计数实时 + 回收站（问题4/9/10/12）

**Files:**
- Modify: `backend/app/api/v1/elements.py:259-310`（list_pages / get_page_tree）
- Modify: `backend/app/services/element_asset_service.py:132-142`（list_recycled）
- Test: `backend/tests/test_element_asset_service.py`（或新文件 test_element_mgmt_fixes.py）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_element_mgmt_fixes.py`（参照 test_element_asset_service.py 的 fixture 模式——先读该文件开头 40 行照抄其 db/session 桩方式；若是真 DB 测试则照真 DB 模式）：

```python
# -*- coding: utf-8 -*-
"""元素管理批量修复（问题4/9/10/12）：排序/实时计数/回收站列+倒序"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# TODO(subagent): 打开 test_element_asset_service.py 看它的 fixture（大概率先例是
# patch AsyncSession 或用 sqlite+aiosqlite 内存库），照抄同一套 setup，然后写：

async def test_pages_sorted_by_sort_order(db_fixture):
    """问题4：/pages 与 /pages/tree 按 (sort_order, created_at) 排序"""
    # 建 3 个页面 sort_order 分别 2/0/1（同 created_at 或按序创建）
    # GET /api/v1/elements/pages?project_id=... → 返回顺序应为 sort_order 0/1/2
    # GET /api/v1/elements/pages/tree?project_id=... → data 顺序同
    ...

async def test_tree_element_count_realtime(db_fixture):
    """问题9：树徽标用实时 active COUNT，不用冗余 element_count"""
    # 页面冗余 element_count=5（或默认0），实际该页 active 元素 2 条 + deleted 1 条
    # GET /pages/tree → 该节点 element_count == 2
    ...

async def test_recycle_bin_has_page_name_and_sorted(db_fixture):
    """问题10/12：回收站返回 page_name 且按 recycled_at 倒序"""
    # 两个页面各回收 1 元素，recycled_at A>B
    # GET /api/v1/recycle-bin?project_id=... → data[0].page_name 非空；
    # data[0].recycled_at > data[1].recycled_at
    ...
```

（subagent 注意：上面是行为规约。具体 fixture/断言写法**必须**先读 `backend/tests/test_element_asset_service.py` 现有 setup——它已有 create_sub_page/move_page 测试（307-390 行），复用同一套建页/建元素 helper。若现有测试文件用 fakeredis/AsyncMock 桩，则本测试同款；端点层测试可参照 test_api_capture_session.py 的 TestClient 模式 patch db。）

- [ ] **Step 2: 跑红**

`cd /d/MoonTest/backend && python -m pytest tests/test_element_mgmt_fixes.py -x -q` → FAIL

- [ ] **Step 3: 实现**

elements.py `list_pages`（270-274 行）排序改：

```python
    result = await db.execute(
        select(PageRepository)
        .where(PageRepository.project_id == project_uuid)
        .order_by(PageRepository.sort_order, PageRepository.created_at)
    )
```

elements.py `get_page_tree`（291-296 行）同样改 order_by，并在 nodes 组装（298-302 行）后加实时计数：

```python
    # 问题9：element_count 实时化（冗余字段只增不减，回收/删除路径不维护 → 徽标漂移）
    from sqlalchemy import func as _func
    counts = await db.execute(
        select(ElementRepository.page_id, _func.count(ElementRepository.id))
        .where(ElementRepository.project_id == project_uuid,
               ElementRepository.status == "active",
               ElementRepository.page_id.isnot(None))
        .group_by(ElementRepository.page_id)
    )
    count_map = {pid: n for pid, n in counts.all()}
    for p in pages:
        nodes[p.id]["element_count"] = count_map.get(p.id, 0)
```

（确认 elements.py 顶部已 import ElementRepository；没有则加。）

element_asset_service.py `list_recycled`（136-141 行）加排序：

```python
        result = await db.execute(
            select(ElementRepository).where(
                ElementRepository.project_id == uid,
                ElementRepository.status == "deleted",
            ).order_by(ElementRepository.recycled_at.desc().nullslast())
        )
```

elements.py `recycle_bin` 端点（约 1024 行）改附 page_name：

```python
    els = await ElementAssetService(db).list_recycled(project_id)
    return {"code": 0, "data": await ElementAssetService(db).attach_page_names(els)}
```

- [ ] **Step 4: 跑绿 + 回归**

`python -m pytest tests/test_element_mgmt_fixes.py -q` 全 PASS；`python -m pytest -q` 全 PASS（800+）

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/elements.py backend/app/services/element_asset_service.py backend/tests/test_element_mgmt_fixes.py
git commit -m "fix(elements): 页面排序按sort_order+树计数实时化+回收站页面列与倒序(问题4/9/10/12)"
```

---

### Task 2: 后端——verify 端点走 Proactor 桥（问题8）

**Files:**
- Modify: `backend/app/api/v1/elements.py:1179-1197`（verify_element_locator）
- Test: `backend/tests/test_element_mgmt_fixes.py`

- [ ] **Step 1: 写失败测试**

在 test_element_mgmt_fixes.py 追加（TestClient 模式，参照 test_api_capture_session.py）：

```python
def test_verify_locator_uses_bridge(client, ):
    """问题8：verify 端点 Playwright 操作经 _bridge.run 投递（Selector loop 不支持子进程）"""
    with patch("app.api.v1.elements._bridge") as mock_bridge, \
         patch("app.api.v1.elements.PlaywrightService") as mock_pw_cls:
        # mock bridge.run 直通执行协程
        import asyncio
        async def _passthrough(coro):
            return await coro if asyncio.iscoroutine(coro) else coro
        mock_bridge.run = _passthrough
        pw = MagicMock()
        mock_pw_cls.return_value = pw
        # pw.start/pw.close 是 async；pw.browser.new_page async；链式都在 bridge 里跑
        pw.start = AsyncMock(return_value=None)
        pw.close = AsyncMock(return_value=None)
        page = MagicMock()
        page.goto = AsyncMock(return_value=None)
        page.close = AsyncMock(return_value=None)
        pw.browser = MagicMock()
        pw.browser.new_page = AsyncMock(return_value=page)
        # db 层：元素/页面/环境 —— 参照现有 verify 测试或 patch db.get/select
        # （subagent：若 db 桩复杂，可将 verify 逻辑抽 helper 测 helper；端点测试至少断言 _bridge.run 被用）
        ...
    # 断言：不抛 NotImplementedError（即未在宿主 loop 直接跑子进程）；
    # 简化断言：mock_bridge.run 被调用（Playwright 操作全经桥）
```

（subagent：此测试重点在**断言 Playwright 调用经 _bridge**。若端点 db 依赖桩太重，允许改为抽 `_verify_locator_request` helper 函数测它接收 bridge 参数；或仅做实现评审 + 真浏览器验收兜底。先读现有 verify 相关测试有没有先例。）

- [ ] **Step 2: 跑红 → Step 3: 实现**

elements.py verify 端点体（1179-1197）改为：

```python
    from app.services.element_asset_service import verify_locator_on_page
    pw = PlaywrightService()
    page = None
    try:
        await _bridge.run(pw.start(headless=True))
        target_url = env.url.rstrip("/") + (page_row.page_url or "")
        page = await _bridge.run(pw.browser.new_page())
        await _bridge.run(page.goto(target_url, timeout=30000, wait_until="networkidle"))
        result = await _bridge.run(verify_locator_on_page(
            page, {"type": request.locator_type, "value": request.locator_value,
                   "score": request.score or 0}))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"页面打开失败: {str(e)[:200]}")
    finally:
        if page:
            try:
                await _bridge.run(page.close())
            except Exception:
                pass
        try:
            await _bridge.run(pw.close())
        except Exception:
            pass
    return {"code": 0, "data": result}
```

（`_bridge` 已在文件头 import——56 行。pw.start/pw.close 返回协程，_bridge.run 接收协程；注意 `pw.start(headless=True)` 调用本身在宿主 loop 创建协程对象没问题，真正 await 在桥内执行。）

- [ ] **Step 4: 绿 + 回归 → Step 5: Commit**

```bash
git add backend/app/api/v1/elements.py backend/tests/test_element_mgmt_fixes.py
git commit -m "fix(elements): 校验定位器走Proactor桥(修Windows Selector loop NotImplementedError 502)"
```

---

### Task 3: 后端——会话抓取高亮视口坐标（问题2）

**Files:**
- Modify: `backend/app/api/v1/elements.py`（capture_browser_page 端点 + add_capture_batch 透传 + 新 helper）
- Test: `backend/tests/test_element_mgmt_fixes.py` 或 test_api_capture_session.py

- [ ] **Step 1: 写失败测试**

```python
def test_capture_elements_have_viewport_box(client, mgr):
    """问题2：会话抓取元素附 _viewport_box（视口坐标），高亮框不再错位"""
    # mock scan/_verify 返回 1 个元素（文档坐标 y=800，视口 bounding_box y=100）
    # POST capture → data.elements[0]._viewport_box == {"x":..,"y":100,...}
    ...
```

（照抄 test_api_capture_session.py 的 `test_capture_passes_include_div_text` patch 集合：patch `app.api.v1.elements.scan_interactive_elements`、`_verify_elements`、storage、CaptureSessionService。_verify_elements 返回元素 dict 需含 semantic_info。新增 patch：elements.py 里将调用的 `bounding_box` —— 由于 raw_elements 是 mock dict 不是真 Locator，实现上 _collect_viewport_boxes 接收 page+raw_elements、对每个 elem 调 elem.bounding_box()——mock 元素是 AsyncMock 即可设 bounding_box 返回值。）

- [ ] **Step 2: 跑红 → Step 3: 实现**

elements.py 加 helper（_verify_elements 附近）：

```python
async def _collect_viewport_boxes(page, raw_elements) -> list:
    """对每个原始元素取视口坐标 bounding_box（会话截图是视口截图，高亮框专用）。"""
    boxes = []
    for elem in raw_elements:
        try:
            b = await elem.bounding_box()
            boxes.append({
                "x": int(b["x"]), "y": int(b["y"]),
                "width": int(b["width"]), "height": int(b["height"]),
            } if b else None)
        except Exception:
            boxes.append(None)
    return boxes
```

capture_browser_page 中 `_verify_elements` 之后加：

```python
    # 会话截图是视口截图 → 高亮框须用视口坐标；文档坐标（semantic.coords）供入库/转脚本
    viewport_boxes = await _bridge.run(_collect_viewport_boxes(page, raw_elements))
    for el, vb in zip(elements, viewport_boxes):
        el["_viewport_box"] = vb
```

`add_capture_batch` 端点组装 elements 的 dict 里（519 行 attributes 之后）加：`"_viewport_box": d.get("_viewport_box"),`

注意：`_verify_elements` 返回的 elements 与 raw_elements 按 index 一一对应（前者由后者逐个生成，`continue` 跳过的会错位！）——**实现时改为在 _verify_elements 内部**：给每个 verified element 记录其源 elem 的 viewport box（在 724-757 行循环内，生成 verified dict 时取 `bounding_box`），这样天然对齐。采用此方案：

```python
    # _verify_elements 循环内，semantic 提取后：
    try:
        vb = await elem.bounding_box()
        viewport_box = {"x": int(vb["x"]), "y": int(vb["y"]),
                        "width": int(vb["width"]), "height": int(vb["height"])}
    except Exception:
        viewport_box = None
    # verified_elements.append({... 现有字段 ..., "_viewport_box": viewport_box})
```

（adopt 此方案则无需新 helper 与 zip；测试 patch _verify_elements 直接返回带 _viewport_box 的 dict。）

- [ ] **Step 4: 绿 + 回归 → Step 5: Commit**

```bash
git add backend/app/api/v1/elements.py backend/tests/test_element_mgmt_fixes.py
git commit -m "fix(elements): 会话抓取元素补视口坐标_viewport_box(修高亮框文档坐标错位)"
```

---

### Task 4: 前端——ElementList 页面树/新建定位器/抽屉合并/调序/回收站（问题3/5/6/7/10）+ element.js 路径（问题11）

**Files:**
- Modify: `frontend/src/views/ElementList.vue`
- Modify: `frontend/src/api/element.js:142-149`
- Verify: `cd /d/MoonTest/frontend && npm run build`

- [ ] **Step 1: element.js 路径修复（问题11）**

```javascript
  async exportElements(projectId) {
    const response = await axios.get('/elements/elements-export', { params: { project_id: projectId } })
    return response.data
  },
  async importElementsAsset(projectId, payload) {
    const response = await axios.post('/elements/elements-import', { project_id: projectId, payload })
    return response.data
  },
```

（读 140-150 行现文，仅改 URL 字符串。）

- [ ] **Step 2: loadPages 改树接口（问题3）**

`loadPages`（390 行）改：

```javascript
const loadPages = async () => {
  try {
    const response = await elementAPI.getPageTree(projectId.value)
    pages.value = (response && response.data) || response || []
  } catch (e) {
    console.error('加载页面树失败:', e)
    pages.value = []
  }
}
```

左栏模板（36-47 行的扁平 v-for div）改 el-tree：

```html
        <div
          class="tree-node" :class="{ active: treeFilter.mode === 'all' }"
          @click="selectNode('all')"
        >📁 全部元素</div>
        <el-tree
          :data="pages"
          node-key="id"
          :props="{ label: 'page_name', children: 'children' }"
          default-expand-all
          :expand-on-click-node="false"
        >
          <template #default="{ data }">
            <span
              class="tree-node page-node"
              :class="{ active: treeFilter.mode === 'page' && treeFilter.pageId === data.id }"
              @click="selectNode('page', data.id)"
              @contextmenu.prevent="openCtxMenu($event, data)"
            >📄 {{ data.page_name }} <span class="count">({{ data.element_count ?? 0 }})</span></span>
          </template>
        </el-tree>
```

（样式：`.tree-node.page-node` 在树内 display 保持 inline-flex；必要时加 `.el-tree .tree-node { display: inline-flex; }` 微调。）

- [ ] **Step 3: 新建元素带定位器（问题5）**

createForm（搜 `createForm = ref`）加 `locators: []`；新建弹窗表单（所属页面 form-item 之后）加：

```html
        <el-form-item label="定位器">
          <div style="width:100%">
            <div v-for="(loc, i) in createForm.locators" :key="i" style="display:flex; gap:6px; margin-bottom:6px">
              <el-select v-model="loc.type" style="width:120px" size="small">
                <el-option v-for="t in ['id', 'css', 'data-testid', 'text', 'xpath']" :key="t" :label="t" :value="t" />
              </el-select>
              <el-input v-model="loc.value" placeholder="定位表达式" size="small" style="flex:1" />
              <el-input-number v-model="loc.score" :min="0" :max="150" size="small" style="width:100px" />
              <el-button size="small" type="danger" text @click="createForm.locators.splice(i, 1)">删除</el-button>
            </div>
            <el-button size="small" text type="primary" @click="createForm.locators.push({ type: 'css', value: '', score: 50 })">+ 添加定位器</el-button>
          </div>
        </el-form-item>
```

submitCreate 的 payload `locators: []` 改：

```javascript
      locators: (form.locators || [])
        .filter((l) => (l.value || '').trim())
        .map((l) => ({ type: l.type, value: l.value.trim(), score: l.score, source: 'manual' })),
```

同时 submitCreate 开头加校验：`if ((form.locators || []).some((l) => (l.value||'').trim() && !l.type))` → warning「定位器需选类型」。

- [ ] **Step 4: 抽屉定位器合并 + 调序/刷新修复（问题6/7）**

4a) 模板：删掉 152-157 行**两个** section-title（「按置信度排序」「数组原序」两个标题及其按钮），替换为一个：

```html
        <div class="section-title">
          定位器 ({{ drawerLocators.length }})
          <el-button size="small" text type="primary" :icon="Plus" @click="locatorDialogVisible = true">自定义定位器</el-button>
        </div>
```

4b) script：

```javascript
// 抽屉定位器：按 score 倒序展示（★首选=第一行）；↑↓ 用原序 index 换算提交
const drawerLocators = computed(() =>
  extractLocators(detailRow.value).slice().sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
)
const primaryIndex = computed(() => (drawerLocators.value.length ? 0 : -1))

// score 倒序视图 index → 数组原序 index（后端按原序交换）
const originalIndex = (sortedIdx) => {
  const raw = extractLocators(detailRow.value)
  const target = drawerLocators.value[sortedIdx]
  return raw.indexOf(target)
}
```

4c) `reorder` 整体替换（删除本地交换逻辑）：

```javascript
const reorder = async (sortedIdx, direction) => {
  const el = detailRow.value
  if (!el) return
  const rawIdx = originalIndex(sortedIdx)
  if (rawIdx < 0) return
  try {
    await elementAPI.reorderLocator(el.id, rawIdx, direction)
    await reloadElement(el.id)
  } catch (e) {
    ElMessage.error('调序失败: ' + (e.message || e))
  }
}
```

4d) 新增 `reloadElement`（loadElements 附近）：

```javascript
// 按 id 重查单个元素更新抽屉（分页信封与平铺两形态兼容；问题6b 刷新断点）
const reloadElement = async (elId) => {
  try {
    const response = await elementAPI.listElementsAsset(projectId.value, {
      scope: treeFilter.value.mode === 'page' ? undefined : (scopeFilter.value || undefined),
      pageId: treeFilter.value.mode === 'page' ? treeFilter.value.pageId : undefined,
      keyword: keyword.value || undefined,
      page: 1, pageSize: 100,
    })
    const data = (response && response.data) || {}
    const items = data.items || (Array.isArray(data) ? data : [])
    elements.value = items
    const fresh = items.find((e) => e.id === elId)
    if (fresh) {
      detailRow.value = fresh
    } else {
      ElMessage.warning('已保存，列表分页未包含该元素，请刷新查看')
      loadElements()
    }
  } catch {
    loadElements()
  }
}
```

4e) `submitLocator` 收尾改：删除现「重拉列表并 find」整段（668-688 行的 try 内后半段），改为：

```javascript
    await elementAPI.addLocator(el.id, newLocator.value.type, newLocator.value.value, newLocator.value.score)
    ElMessage.success('定位器已添加')
    locatorDialogVisible.value = false
    newLocator.value = { type: 'css', value: '', score: 50 }
    await reloadElement(el.id)
```

- [ ] **Step 5: 回收站页面列（问题10 前端）**

回收站表格（252 行）名称列后加：

```html
        <el-table-column prop="page_name" label="所属页面" width="140" show-overflow-tooltip />
```

（后端 Task 1 已附 page_name。）

- [ ] **Step 6: build 验证**

`cd /d/MoonTest/frontend && npm run build` → 成功

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/ElementList.vue frontend/src/api/element.js
git commit -m "fix(elements): 页面树层级/新建带定位器/抽屉定位器合并+调序刷新/回收站页面列/导出路径(问题3/5/6/7/10/11)"
```

---

### Task 5: 前端——会话工作台高亮用视口坐标（问题2 前端）

**Files:**
- Modify: `frontend/src/components/element/CaptureWorkbench.vue`（highlightElements computed）

- [ ] **Step 1: highlightElements 改用 _viewport_box**

现有 computed（搜 `highlightElements`）改为：

```javascript
// 高亮框用视口坐标（会话截图是视口截图）；_viewport_box 缺失回退文档坐标（旧会话兼容）
const highlightElements = computed(() =>
  (stagingState.value?.elements || []).map((el) => {
    const vb = el._viewport_box
    return {
      ...el,
      element_text: el._nameDraft || el.element_text || el.temp_id,
      position_x: vb ? vb.x : el.position_x,
      position_y: vb ? vb.y : el.position_y,
      width: vb ? vb.width : el.width,
      height: vb ? vb.height : el.height,
    }
  })
)
```

- [ ] **Step 2: build → Commit**

```bash
git add frontend/src/components/element/CaptureWorkbench.vue
git commit -m "fix(elements): 会话高亮框优先用视口坐标(问题2 根治——文档坐标与视口截图错位)"
```

---

### Task 6: 全量回归 + 验收清单

- [ ] 后端 `python -m pytest -q` 全 PASS（800+新增）
- [ ] 前端 `npm run build` 成功
- [ ] 按用户规则输出验收清单（序号/原始描述/原因/修改方案/涉及功能点验证步骤）
