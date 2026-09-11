# 元素管理批量修复（问题3-8）设计文档

日期：2026-09-11 ｜ 状态：用户已确认设计，待出实施计划

## 背景

验收反馈 6 个问题（3/4/5/6/7/8），根因均已查明。用户已确认决策：
- 问题3：ElementList 页面树改用嵌套树接口（后端已有）
- 问题4：列表排序改按 sort_order（后端已交换值但不排它）
- 问题5：新建元素弹窗加定位器编辑（后端 locators 字段已支持，前端写死 []）
- 问题6：抽屉**合并为一个「定位器」区块**（按 score 倒序 + 首选★ + ↑↓ 调序），修保存后不刷新
- 问题7：reorder 移除前端本地错位交换，以后端为准重拉
- 问题8：verify 端点 Playwright 操作经 `_ProactorBridge` 投递（修 Windows Selector loop NotImplementedError → 502）

## 根因明细

| # | 现象 | 根因 |
|---|---|---|
| 3 | 页面树同级展示无层级 | ElementList.vue 左栏用扁平 `/elements/pages` 循环渲染 div；后端 `/pages/tree`（按 parent_id 嵌套）现成未接 |
| 4 | 上移/下移接口 200 但顺序不变 | `/pages` 与 `/pages/tree` 排序 `order_by(last_fetch_at desc)`，不含 sort_order——交换白换 |
| 5 | 新建元素不能填定位器 | `submitCreate` 写死 `locators: []`（ElementList.vue:789）；后端 ElementCreateRequest.locators + create_element 已支持 |
| 6a | 两个「定位器」标题 | 半成品 UI：两个标题渲染同一 drawerLocators（数组原序），第一个无排序逻辑 |
| 6b | 自定义定位器保存后不显示 | submitLocator 重拉后 `fresh = elements.value.find(...)` 在分页信封下找不到（元素不在当前页/过滤）→ detailRow 不更新 |
| 7 | ↑↓ 不好使 | 后端按数组原序 index 交换；前端 reorder 成功后又本地按 score 倒序再交换 → index 与展示序错位 |
| 8 | 校验首选 502 NotImplementedError | verify 端点在 uvicorn Windows SelectorEventLoop 直接 `PlaywrightService().start()`（Selector loop 不支持子进程）；browser_session_manager 已有 _ProactorBridge 方案未复用 |

## 设计

### 1. 问题3：页面树嵌套展示（ElementList.vue）

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

### 5. 问题8：verify 走 Proactor 桥（后端）

`elements.py` verify 端点（1179-1197 行）Playwright 调用全部经 `_bridge.run`（`from app.services.browser_session_manager import _bridge`，文件头已 import）：
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

后端 TDD（pytest，element_asset_service 已有测试文件模式可循）：
1. 问题4：list 排序——mock/真 DB 建 3 页面 sort_order 2/0/1 → `/pages` 返回顺序 0/1/2（`/pages/tree` 同）
2. 问题8：verify 端点 mock `_bridge.run` 断言被调用且不直接 `pw.start`（或 mock 后返回 hit 结果）
3. 问题5：create_element 已有测试，补 locators 透传断言（可能已有，确认即可）
4. 回归：全量 pytest 全绿

前端：`npm run build` + 真浏览器验收（树层级缩进 / 上移下移生效 / 新建带定位器 / 抽屉单区块 / 添加定位器立即可见 / ↑↓ 生效 / 校验不再 502）

## 不做项

- 定位器 score 手动编辑（保持后端重算 150-pos*10）
- verify 端点的登录态注入（现状已走激活环境 URL，本次只修 502）
