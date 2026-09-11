# 元素管理批量修复（问题3-10 + 问题2红框闪烁）设计文档

日期：2026-09-11 ｜ 状态：用户已确认设计，待出实施计划

## 背景

验收反馈 9 个问题（2/3/4/5/6/7/8/9/10），根因均已查明。用户已确认决策：
- 问题3：ElementList 页面树改用嵌套树接口（后端已有）
- 问题4：列表排序改按 sort_order（后端已交换值但不排它）
- 问题5：新建元素弹窗加定位器编辑（后端 locators 字段已支持，前端写死 []）
- 问题6：抽屉**合并为一个「定位器」区块**（按 score 倒序 + 首选★ + ↑↓ 调序），修保存后不刷新
- 问题7：reorder 移除前端本地错位交换，以后端为准重拉
- 问题8：verify 端点 Playwright 操作经 `_ProactorBridge` 投递（修 Windows Selector loop NotImplementedError → 502）
- 问题9：树徽标计数与列表条数不一致 → 树计数改实时 COUNT
- 问题10：回收站弹窗加「所属页面」列
- 问题11：导出 404 → 前端 API 路径少了 `/elements` 前缀
- 问题12：回收站按回收时间倒序（现按 DB 默认序返回）
- 问题2（红框无橘色闪烁）：会话截图是视口截图，元素坐标是文档坐标——页面滚动过/元素在首屏外时框全部错位或落出截图，用户无法 hover 到框。修法：staging 元素补视口坐标，工作台高亮用视口坐标

## 根因明细

| # | 现象 | 根因 |
|---|---|---|
| 2 | hover 行无橘色闪烁 | 坐标系错位：会话截图 page.screenshot() 默认视口截图（elements.py:711），元素 position_x/y 来自 extract_semantic_info 的**文档坐标**（rect+scroll，21eded4 为一次性抓取 full_page 改的）——页面滚动过或元素在首屏外时框错位/落出 img，无法 hover |
| 3 | 页面树同级展示无层级 | ElementList.vue 左栏用扁平 `/elements/pages` 循环渲染 div；后端 `/pages/tree`（按 parent_id 嵌套）现成未接 |
| 4 | 上移/下移接口 200 但顺序不变 | `/pages` 与 `/pages/tree` 排序 `order_by(last_fetch_at desc)`，不含 sort_order——交换白换 |
| 5 | 新建元素不能填定位器 | `submitCreate` 写死 `locators: []`（ElementList.vue:789）；后端 ElementCreateRequest.locators + create_element 已支持 |
| 6a | 两个「定位器」标题 | 半成品 UI：两个标题渲染同一 drawerLocators（数组原序），第一个无排序逻辑 |
| 6b | 自定义定位器保存后不显示 | submitLocator 重拉后 `fresh = elements.value.find(...)` 在分页信封下找不到（元素不在当前页/过滤）→ detailRow 不更新 |
| 7 | ↑↓ 不好使 | 后端按数组原序 index 交换；前端 reorder 成功后又本地按 score 倒序再交换 → index 与展示序错位 |
| 8 | 校验首选 502 NotImplementedError | verify 端点在 uvicorn Windows SelectorEventLoop 直接 `PlaywrightService().start()`（Selector loop 不支持子进程）；browser_session_manager 已有 _ProactorBridge 方案未复用 |
| 9 | 树徽标 (3) 但列表只 1 条 | page.element_count 是**只增不减的冗余计数**（仅 element_service.batch_import_elements:337 累加；回收/删除/手工新建/资产导入都不更新）→ 与实时查询 status=active 的列表必然漂移 |
| 10 | 回收站无所属页面列 | `/recycle-bin` 返回裸 to_dict 列表无 page_name；前端弹窗也没有该列 |

## 设计

### 1. 问题2：会话抓取高亮坐标改视口坐标（后端 + 前端零改动）

根因：staging 元素 position_x/y 是文档坐标（rect+scroll），会话截图是视口截图。
修法：`capture_browser_page` 端点（elements.py:774-777）在 `_verify_elements` 之后补一步视口坐标覆盖——对每个元素 dict：

```python
    # 会话截图是视口截图 → 高亮框须用视口坐标（bounding_box）；
    # 文档坐标（semantic.coords，rect+scroll）供入库/转脚本用，二者分开存
    viewport_boxes = await _bridge.run(_collect_viewport_boxes(page, raw_elements))
    for el, vb in zip(elements, viewport_boxes):
        if vb:
            el["_viewport_box"] = vb
```

新 helper `_collect_viewport_boxes(page, elems)`：对每个 raw element `bounding_box()` 返回 `{"x": int(b["x"]), "y": int(b["y"]), "width": int(b["width"]), "height": int(b["height"])}`（异常返回 None）。

同时 `add_capture_batch`（elements.py:499-519，端点组装 staging 元素处）透传 `_viewport_box`；`CaptureWorkbench.vue` 的 `highlightElements` computed 优先用 `_viewport_box` 映射到 position_x/y/width/height（高亮专用），列表/入库逻辑不变。

一次性抓取（full_page 截图 + 文档坐标）不动。

### 2. 问题3：页面树嵌套展示（ElementList.vue）

- `loadPages` 改调 `elementAPI.getPageTree(projectId)`（API 已有，`/elements/pages/tree` 返回 `{code, data: roots}` 嵌套），取 `res.data`
- 左栏模板改 el-tree（ElementLibrary.vue 已有同款先例）：
  - `:props="{ label: 'page_name', children: 'children' }"` node-key="id" default-expand-all
  - 节点内容：`📄 {{page_name}} ({{element_count ?? 0}})`，@click → selectNode('page', id)，@contextmenu.prevent → openCtxMenu（ctxMenu.page = data）
  - 「全部元素」根节点保留在 el-tree 上方
- 层级视觉：el-tree 自带缩进

### 2. 问题4：排序按 sort_order（后端）

`elements.py` 两处 order_by 改 `.order_by(PageRepository.sort_order, PageRepository.created_at)`：
- `list_pages`（273 行）
- `get_page_tree`（294 行）

### 3. 问题5：新建元素带定位器（ElementList.vue）

- createForm 加 `locators: []`；弹窗表单加「定位器」区：
  - 行：类型 select（id/css/data-testid/text/xpath）+ 值 input + 置信度 el-input-number + 删除按钮
  - 「添加定位器」按钮 append 空行；至少一条时校验值非空
- submitCreate 提交 `locators: form.locators.filter(l => l.value.trim()).map(l => ({type: l.type, value: l.value.trim(), score: l.score, source: 'manual'}))`；空数组传 `[]` 不变
- 后端零改动（ElementCreateRequest.locators 已通）

### 4. 问题6：定位器区块合并 + 刷新修复（ElementList.vue）

- 抽屉删掉双标题，单区块「定位器 (N)」：
  - `drawerLocators` computed 改为 score 倒序：`extractLocators(detailRow.value).slice().sort((a,b) => (b.score??0)-(a.score??0))`
  - 首选★ = 第一行（primaryIndex=0 语义简化：★ 固定第一行）
  - ↑↓ 操作改为「在 score 倒序视图中的 index」→ 提交时换算回数组原序 index：传给后端前用 `originalIdx = extractLocators(detailRow.value).indexOf(sortedLocs[index])`（对象引用相等）
- **刷新修复（同时治 6b/7）**：新方法 `reloadElement(elId)`：
  ```javascript
  const reloadElement = async (elId) => {
    const response = await elementAPI.listElementsAsset(projectId.value, {
      scope: treeFilter.value.mode === 'page' ? undefined : (scopeFilter.value || undefined),
      pageId: treeFilter.value.mode === 'page' ? treeFilter.value.pageId : undefined,
      keyword: keyword.value || undefined,
      page: 1, pageSize: 100,
    })
    const data = (response && response.data) || {}
    const list = data.items || data || []
    elements.value = Array.isArray(list) ? list : elements.value
    const fresh = (Array.isArray(list) ? list : []).find(e => e.id === elId)
    if (fresh) detailRow.value = fresh
  }
  ```
  注意分页信封与平铺两种返回形态都要兼容（带 page 参数返回 items；不带返回数组——这里带 page=1&pageSize=100 走信封，拿 items）。submitLocator 与 reorder 的收尾统一改为 `await reloadElement(el.id)`，删除本地交换逻辑。
- 兜底：fresh 找不到（元素不在前 100 条）→ `ElMessage.warning('已保存，请刷新列表查看')` + `loadElements()`

### 5. 问题8：verify 走 Proactor 桥（后端）`elements.py` verify 端点（1179-1197 行）Playwright 调用全部经 `_bridge.run`（`from app.services.browser_session_manager import _bridge`，文件头已 import）：
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
（pw.start/close 是 async 方法，直接投递协程即可；与 browser_session_manager 同线程复用 Proactor loop。）

## 测试

后端 TDD（pytest）：
1. 问题4：list 排序——3 页面 sort_order 2/0/1 → `/pages` 与 `/pages/tree` 返回顺序 0/1/2
2. 问题9：树接口 element_count 实时——页面冗余 count=5 但 active 元素实际 2 条 → 返回 2
3. 问题10/12：recycle-bin 返回含 page_name 且按 recycled_at 倒序
4. 问题8：verify 端点 mock `_bridge.run` 断言被调用（不直接 pw.start）
5. 问题5：create_element locators 透传断言（确认已有，缺则补）
6. 回归：全量 pytest 全绿

前端：`npm run build` + 真浏览器验收（树层级缩进 / 上移下移生效 / 新建带定位器 / 抽屉单区块 / 添加定位器立即可见 / ↑↓ 生效 / 校验不再 502 / 会话抓取红框闪烁 / 回收站页面列+倒序 / 导出下载）

### 6. 问题9：树徽标计数改实时（后端）

根因：`page.element_count` 只增不减（仅 element_service.batch_import_elements:337 累加；回收/删除/手工新建/资产导入/会话入库路径均不维护）→ 与列表（实时 status=active COUNT）漂移。
修法（最小改）：`get_page_tree` 与 `list_pages` 返回时**实时计算** element_count 覆盖冗余字段：

```python
    # element_count 实时化（冗余字段只增不减，回收/删除路径不维护 → 徽标漂移）
    from sqlalchemy import func as _func
    counts = await db.execute(
        select(ElementRepository.page_id, _func.count(ElementRepository.id))
        .where(ElementRepository.project_id == project_uuid,
               ElementRepository.status == "active",
               ElementRepository.page_id.isnot(None))
        .group_by(ElementRepository.page_id)
    )
    count_map = {pid: n for pid, n in counts.all()}
    # nodes/响应组装处: d["element_count"] = count_map.get(p.id, 0)
```

`page.element_count` 字段保留（其他处引用不破坏），树/列表接口以实时值覆盖。

### 7. 问题10：回收站加所属页面列（后端 + 前端）

- 后端 `recycle_bin` 端点改用 `svc.attach_page_names(els)`（现成方法，附 page_name）
- 前端回收站表格加列：`<el-table-column prop="page_name" label="所属页面" width="140" show-overflow-tooltip />`（在名称列后）

### 8. 问题11：导出/导入 404 —— API 路径修正（前端）

根因：端点挂 `@router`（prefix `/elements`，实际路径 `/api/v1/elements/elements-export`），前端 axios 打 `/elements-export`（缺 `/elements` 段）→ 404。
修法 element.js 两处：
- `exportElements`：`'/elements-export'` → `'/elements/elements-export'`
- `importElementsAsset`：`'/elements-import'` → `'/elements/elements-import'`

### 9. 问题12：回收站按回收时间倒序（后端）

`list_recycled` 加 `.order_by(ElementRepository.recycled_at.desc().nullslast())`。

## 不做项

- 定位器 score 手动编辑（保持后端重算 150-pos*10）
- verify 端点的登录态注入（现状已走激活环境 URL，本次只修 502）
- `page.element_count` 冗余字段的写路径维护（读路径实时化后写路径不再关键，YAGNI）
