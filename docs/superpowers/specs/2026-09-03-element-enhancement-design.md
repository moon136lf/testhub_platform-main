# 元素库增强（原型对齐版）设计

> 创建：2026-09-03
> 输入：`MoonTest元素抓取方案V1.md`（会话式抓取方案）+ `给ClaudeCode的元素库增强提示词.md`（过滤/登录态/点选）+ 原型 `moontest-test-platform.html`（交互事实源）
> 用户决策：**全做**——过滤/调试模式、登录态、结果分组入库、截图高亮点选联动、会话式抓取（辅助登录+storage_state+多页会话）、页面树列表区、定位校验
> 前提：现有一次性抓取链路（SSE 直播→落库→截图代理）刚修通，全部保留。

---

## 0. 分期（提示词要求分两次提交，会话式为第三期）

- **P1（目标A）**：从 URL 抓取弹窗——文本/类型过滤、调试模式、登录态卡片区、结果按页面分组+勾选入库、bounding box 坐标入库（B 阶段依赖）
- **P2（目标B）**：抓取结果截图高亮框 + 右侧元素面板双向联动点选（静态坐标版）
- **P3（方案V1）**：页面树列表区、会话式抓取工作台（辅助登录/会话操作/多页批量入库）、点选定位（活 DOM）、登录态持久化+失效检测、定位校验

## 1. 数据模型

### 1.1 新增表 `login_state`
```sql
CREATE TABLE IF NOT EXISTS login_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    env VARCHAR(20) NOT NULL DEFAULT 'default',
    storage_state_path TEXT,             -- MinIO object key
    cookie_count INTEGER DEFAULT 0,
    localstorage_count INTEGER DEFAULT 0,
    obtained_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'active', -- active/expired
    UNIQUE(project_id, env)
);
```

### 1.2 现有表扩展（幂等 ALTER）
- `page_repository` + `capture_source VARCHAR(20) DEFAULT 'one_shot'`（one_shot/session）
- `element_repository`：`confidence`（已有，0-10 → UI 显示换算 0-100）、`source`（已有，值域扩展 'session'/'pick'）、`last_verified_at`（已有）；+ `valid_status VARCHAR(20) DEFAULT 'unverified'`（active/invalid/unverified）

### 1.3 会话池（Redis，不入库）
`session:{sid}` = {login_state_id, started_at, expires_at(30min), current_url}；TTL 35min。

## 2. 后端接口（全部挂 /elements 下，v1）

### 2.1 一次性抓取扩展（P1）
- `POST /fetch` 增参：`text_filter`（逗号分隔，命中保留）、`type_filter`（如 "button,input"，空=全部）、`debug_mode`（bool，不过滤+返回诊断 svgHref/iconFingerprint）。过滤在 `scan_interactive_elements` 后、定位器生成**前**（省 token/时间）
- `POST /fetch` 返回的 elements 项已有 position/width/height（bounding box）——确认 `extract_semantic_info` 的 coords 即视口坐标并保留（P2 直接用）
- `POST /import` 已支持勾选入库（selected_element_ids + elements_data），无需改

### 2.2 登录态（P1 展示 + P3 持久化）
- `GET /login-state?project_id=` → 摘要（status/cookie_count/localstorage_count/obtained_at），P1 阶段无 login_state 表时返回 status='not_configured'
- `POST /login-state/probe`（P3）：访问探针 URL 检测失效

### 2.3 会话式抓取（P3，全部新增）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /session/start | 启动 headed 浏览器（headless=False 弹窗），注册会话池，返回 session_id |
| POST | /session/{sid}/confirm-login | 用户点「登录完成」：轻量校验（URL 含 login/login.*/signin 则判未通过，force=true 可跳过）→ storage_state 导出 → 存 MinIO + login_state 表 → 进入抓取模式 |
| GET | /session/{sid}/status | {remaining_seconds, current_url, screenshot_url(最新截图key)} |
| POST | /session/{sid}/action | {type: click/fill/back/forward/reload, x?, y?, text?} → 执行 → 返回新截图（P3-简化：截图经 screenshot 代理取） |
| POST | /session/{sid}/capture | 抓当前页（复用 scan+verify+semantic 流水线）→ 返回元素集（含 bounding box），追加到会话的已抓集合 |
| POST | /session/{sid}/pick-element | {x, y} → `page.evaluate("([x,y])=>{const el=document.elementFromPoint(x,y);...}")` 反查活 DOM → 生成 5 种定位+评分（复用 generate_locators_for_element）→ 返回定位卡片数据；点不到时降级最近父元素 text= 定位 |
| POST | /session/{sid}/close | 关浏览器+清会话池 |
| POST | /import-batch | 多页面批量入库：[{page_name, page_url, elements_data}] → 逐页 upsert page_repository + 清旧导入（capture_source='session'） |

实现要点：会话浏览器**不进 Celery**——FastAPI 进程内 asyncio 任务持有 Playwright 对象（ lifespan 内管理）；headed 模式在用户桌面弹出。会话倒计时/超时由 Redis TTL + 访问时惰性校验。

### 2.4 列表区 + 校验（P3）
- `GET /pages`、`GET /pages/{page_id}/elements` 已有，够用（页面树直接用）
- `POST /{element_id}/validate` 新增：取最优定位策略 → 用一次性浏览器（或复用会话）访问该元素所在页面 URL → `page.locator(value).count()` 判定 → 更新 valid_status + last_verified_at → 返回结果

## 3. 前端（ElementLibrary.vue 拆子组件 → frontend/src/components/element/）

### 3.1 页面结构（P3 后终态）
```
元素库页
├─ 工具栏：搜索框 | 类型筛选 | 状态筛选 | [+会话式抓取](主) | [一次性抓取](次) | [刷新]
├─ 左：页面树（el-tree，节点=页面名+元素数徽章，点击加载右侧；底部统计条）
├─ 右：元素大表格（别名[编辑]|类型标签|N策略徽章+tooltip|置信度|校验状态|来源|入库时间|操作[校验/删除]）
├─ 一次性抓取弹窗（P1：原表单迁入 + 过滤区 + 登录态卡片 + debug_mode）
├─ 抓取结果组件（P1/P2：截图高亮框叠加 + 右侧元素面板双向联动 + 勾选保存）
├─ 会话式工作台（P3：登录态卡片四态 + 会话操作区[截图+操作按钮+倒计时] + 已抓页面集合 + 已点选元素 + 直播）
└─ 入库确认弹窗（多页签版，来源标记）
```

### 3.2 交互细节（以原型为准）
- 策略 tooltip：hover 黑底，最优绿框+score
- 高亮框：绝对定位 div 叠加在截图上（bounding box 按 [元素坐标/截图尺寸] 比例缩放），红框默认/选中绿框/hover 加粗；点框→右卡片勾选+滚动可见；点卡片→框闪烁
- 会话倒计时最后 5 分钟变橙
- 登录态卡片四态（未配置灰/登录中蓝/校验未过橙/有效绿）文案按方案 V1 3.2 区域 A
- 空态："暂无元素，去抓取" + 两按钮

## 4. 里程碑与验收

### P1（目标A）验收
1. 一次性抓取弹窗含过滤区/登录态卡/调试模式；text_filter="+,X,删除,新增" 只返回命中元素
2. debug_mode 返回全部+诊断字段
3. 结果按页面分组、可勾选、整页/勾选入库；入库后元素列表可见
4. elements 落库含 bounding box 坐标

### P2（目标B）验收
5. 抓取结果截图上渲染高亮框（红/绿/hover），双向联动正常
6. 点选 3 个元素保存入库成功

### P3（会话式）验收
7. 页面树+元素大表格+统计条可见；点树节点切换右侧
8. 辅助登录 headed 弹出→人工登录→「登录完成」→ login_state 落库（Cookie 数显示）
9. 会话操作（点击/输入/后退）截图刷新；30 分钟倒计时
10. 抓当前页→已抓集合追加；3 页批量入库→页面树新增 3 节点，来源标"会话式"
11. 点选定位：hover 黄框跟随、点击绿框锁定+定位卡片、加入当前页、重复点选提示已加入
12. 失效检测探针红横幅；定位校验失效元素标红可筛选
13. 一次性模式不回归

## 5. 约束
- 登录账密仅存后端（沿用项目表或 .env，前端脱敏展示）
- 不破坏现有进度直播/变更检测/SSE 链路
- 会话式链路零 token（自愈 L3+ 才用 AI，与方案 V1 第八节一致）
- 每期独立提交、全量测试绿后再进下一期
