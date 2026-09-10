# 会话式抓取元素列表补齐 + 文本抓取范围扩展 设计文档

日期：2026-09-10 ｜ 状态：用户已确认设计，待出实施计划

## 背景

三阶段验收反馈问题2：会话式抓取工作台元素列表功能补齐。用户需求清单：全选、一键入库、悬浮高亮、框选标注、别名编辑、入库用别名、策略展示。另查明两个相邻问题一并修：面包屑「首页」链接抓不到（无 href 的 `<a>` 不在 `a[href]` 选择器范围）、统计卡片 div 文本抓不到（div 不在 TEXT_SELECTORS）。

用户已确认的 4 个决策：
1. 悬浮高亮+框选标注 → **复用 ElementHighlight 双向联动模式**（与一次性抓取一致）
2. 别名编辑 → **列表内联编辑**（不用入库弹窗）
3. 策略展示 → **行内计数 + 悬浮 popover 详情**
4. 文本扩展 → **「抓展示文本」开关，默认开**（避免所有页面默认元素量翻倍）

## 现状与根因

- 会话式抓取：`frontend/src/components/element/CaptureWorkbench.vue`（左栏裸 img 截图 + 右栏 staging 列表）；staging 状态存 Redis（`capture_session_service.py`），元素含 temp_id/included/batch_idx/position_x/y/width/height/locator_strategies/semantic_info/attributes/element_type/element_text。**无 element_name 字段、无 rename 端点。**
- 全选/全不选已存在（`set_all_included`，前端按钮已有）；入库走 `POST /capture/sessions/{sid}/import`。
- 入库链路：`import_from_capture_session`（elements.py:560）组装 selected_elements → `ElementService.batch_import_elements`（element_service.py:175）。**batch_import 已支持自定义别名**：`element_name` 非空则直接采用（user_name 分支，element_service.py:303-305），否则按中文默认序号（按钮1/输入框1…）。
- 扫描器：`playwright_locator_core.py` `scan_interactive_elements`；INTERACTIVE_SELECTORS 含 `a[href]`（**无 href 的 a 漏**）；TEXT_SELECTORS = span/p/h1-h4/label/td/th（**div 漏**）。
- ElementHighlight.vue（一次性抓取用）：截图上叠加定位框，双向联动（hover 框↔列表行），props: screenshotUrl/elements/selectedIds/hoverId，events: pick/card-hover。

## 设计

### 1. 左栏截图 → ElementHighlight 复用（悬浮高亮 + 框选标注）

CaptureWorkbench ready 阶段左栏：裸 img 替换为 ElementHighlight：
- `:screenshot-url="screenshotSrc"`（base64 dataURL 直接可用）
- `:elements="stagingState.elements"`（含 position_x/y/width/height）
- `:selected-ids` = 勾选元素 temp_id 列表（勾选=绿框，未勾选=红框）
- `:hover-id` + `@card-hover`：列表行 mouseenter → hoverId → 框橘色闪烁 + 名称标签（框选标注）；`@pick`（点击框）→ 列表对应行 scrollIntoView + 短暂高亮
- 点选补抓模式（pickMode）保留原裸 img 点击逻辑：pickMode 开启时 ElementHighlight 的框 pointer-events 需让位给点选——实现上 pickMode 开启时仍渲染 ElementHighlight 但其 pick 事件在 pickMode 下走点选补抓（或 pickMode 时隐藏 hotspot 层，取简单方案：**pickMode 开启时 ElementHighlight 不渲染 hotspot 交互（pointer-events:none），点选走原 onShotClick**）

已知边界（记录不改）：会话截图是视口截图，元素坐标是文档坐标，超一屏的元素框会落出截图范围（一次性抓取 full_page 截图无此问题）。

### 2. 列表行重构（右栏）

每行：`☑ [类型tag] [别名输入框] [N 策略▸popover] [批次tag] [×]`

- **别名内联编辑**：el-input（size=small），model 初始值 = `el.element_name || el.element_text || temp_id`，blur 或回车提交（值变化才调 API）→ 新端点 `POST /capture/sessions/{sid}/elements/rename`，body `{temp_id, element_name}`；服务层 `CaptureSessionService.rename_element`（写 `state["elements"][temp_id]["element_name"]`，截断 100 字）。失败 ElMessage.warning，不阻塞列表。
- **策略展示**：行内「N 策略」文字按钮 + el-popover（trigger=hover）展开全部策略：每行 `{{type}}: {{value}} (score {{score}})`，value 超长截断加 title。
- **入库用别名**：`import_from_capture_session` 组装 selected_elements 时 `"element_name": e.get("element_name") or sem.get("aria_label")`（现已是这个表达式，**确认无需改动**；rename 写入的 element_name 自然流入）。batch_import 的 user_name 分支已消费。

### 3. 全选 / 一键入库

- 全选/全不选按钮已有，保留。
- 入库按钮文案改为「一键入库 (N)」（N=included_count），逻辑不变（页面归属 new/existing 选择保留——需求文档的入库确认语义）。

### 4. 文本抓取范围扩展（开关「抓展示文本」，默认开）

`scan_interactive_elements(page, include_text=False, include_div_text=True)`：
- 新增扫描轮（在 TEXT_SELECTORS 之后）：`div` 叶子节点（`el.evaluate("el => el.children.length === 0")` 且 inner_text 非空 ≤100 字且可见）+ `a:not([href])`（无 href 链接，修面包屑盲区）
- 去重复用 seen_coords（坐标相同只留一个，滤嵌套 div 与已抓的 span 重叠）
- 类型归一：div 叶子 → element_type 保留 "div"；无 href a → "link"
- 透传：
  - 会话抓取端点 `POST /capture/browser/{sid}/capture` 加 query `include_div_text: bool = True`；CaptureWorkbench 加开关「抓展示文本」（默认开，与「抓菜单栏」并排）
  - 一次性抓取：`ElementFetchRequest` 加字段 `include_div_text: bool = True`，`fetch_elements_task` 透传，FetchDialog.vue 加开关
- 风险：元素量增加（展示页 div 叶子多）；坐标去重滤嵌套；定位策略走现有 text/css 生成与评分，无特殊处理
- element_id 去重安全：text+坐标后缀规则已覆盖

### 5. 不做项

- canvas 图表（ECharts）内部元素：DOM 扫描原理限制，不支持；记入 ACCEPTANCE_CHECKLIST 已知问题
- 会话视口截图的滚动偏移补偿：不做
- 入库确认弹窗：不做（内联编辑已覆盖别名诉求，页面归属保留原表单）

## 测试

后端 TDD（pytest）：
1. rename 端点：成功改名 / 元素不存在 404 / 超 100 字截断
2. import 用别名：staging 元素带 element_name → 入库后 element_repository.element_name 为该值（已有 user_name 分支，集成测试确认）
3. include_div_text 扫描：div 叶子抓到 / 非叶子 div 不抓 / 无 href a 抓到 / 有 href a 不在 div 轮重复 / 开关关时不抓
4. capture 端点透传 include_div_text

前端：`npm run build` + 手工验收（悬浮高亮/框标注/别名改后入库生效/策略 popover/开关）

## 验收点（对应用户需求清单）

| 需求 | 实现方式 |
|---|---|
| 全选 | 已有，保留 |
| 一键入库 | 按钮改名+计数，逻辑不变 |
| 悬浮高亮 | 列表行 hover → 截图框橘色闪烁 |
| 框选标注 | hotspot 上显示名称标签；点框→列表行定位 |
| 别名编辑 | 列表内联输入框，blur/回车提交 |
| 入库用别名 | rename 写入 → import 链路已有 user_name 分支 |
| 策略展示 | 行内「N 策略」+ hover popover 详情 |
| 展示文本抓取 | 「抓展示文本」开关默认开（div 叶子 + 无 href a） |
