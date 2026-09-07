# SESSION HANDOFF — 2026-09-04 系统重构方案（沟通定稿 + 已修 bug 清单）

> 本轮性质：**重构方案设计日**。全天与用户头脑风暴定稿了平台重构三阶段方案 + 沟通过程中修了一批阻塞性 bug。
> 下次会话的入口：**阶段1（元素资产）实施计划尚未写**，写完发用户确认后 TDD 动工。

---

## 一、重构方案（已定稿，三级推进，用户已接受）

### 用户核心诉求（原话要点，决策依据）
- 用户是功能测试，不写代码；想让 AI 写自动化框架，人工填/改元素定位
- UI 自动化定位 = **回归/冒烟层**，不替代功能测试（对齐/居中/图标/联动等细节仍靠人）——用户自己想通的，已达成共识
- 平台第一验收标准 = **平台测自己**（抓仪表盘元素→生成用例→评审→转脚本→执行→自愈闭环）
- 核心痛点：脚本转出来**没地方看**——步骤化脚本编辑器由此提为阶段2必做
- 菜单太乱，要重组
- **回归测试独立成页**（不删，先隐藏代码可恢复）：UI 自动化与回归自动化分开；白盒生成的回归用例自动归入用例管理（标识来源），评审精修转自动化后按标记进回归集

### 菜单结构（定稿）

```
仪表盘（单独）
项目管理（单独）
用例资产：用例管理 / 用例评审与精修 / AI智能用例生成（测试规则并入页内，生成历史变页内Tab）
知识库（单独）
元素资产：元素抓取 / 元素管理（页面树+全局元素+多定位器）
自动化：用例转自动化脚本 / UI自动化测试（测试集+执行+记录Tab） / 回归自动化（独立页，隐藏不删）
白盒测试（单独，记录+报告自闭环）
接口与执行（不动，二期）
系统设置（不动）
执行记录与报告菜单取消 → 执行记录/报告并入 UI自动化 和 回归自动化 各自的 Tab
```

### 数据/逻辑设计要点

1. **回归集归属**：test_case/script_asset 加 `for_regression` 标记；白盒生成自动置 true；UI自动化页加「加入回归集」按钮；回归页数据源从 included 标记改为 for_regression
2. **测试集**（阶段2）：test_set 模型（name/source/case_ids/last_run/pass_rate/status）；转脚本页"存为测试集"写入；UI自动化页执行
3. **步骤化脚本编辑器**（阶段2 必做）：每行=动作（操作类型下拉 navigate/click/input/select/wait/assert + **assert_db 数据库断言** + 元素选择器 + 参数），保存生成 Playwright 代码——"不懂代码也能改"的关键件
4. **登录态复用**（阶段3）：Playwright storage_state；test_env.credentials 扩展 login 配置块（login_url/选择器/账密/success_check/state_ttl）；每条用例独立 context + 免登录；失败跳登录页自动刷新 state 重试一次。业界方案对比结论：storage_state 优于"复用登录页面"（隔离性）也优于"每条复登"（速度）
5. **定位器置信度统一**（阶段1 核心，需求对齐）：
   - 现状缺陷：抓取端 priority 写死类型序（id>css>role>text>xpath），消费端 `_strategy_to_playwright` 又是另一套序（role>text>label>placeholder>css），互相对不上；用户调序不生效
   - 定稿：每条定位器一个综合 score（0-100）= 抓取类型基准 + 当场验证加成（命中唯一+10/命中多-20）+ 自愈运行期 ±1 + **用户手动调序最高优先**；消费端 find() 按 score 降序取首选，首选失败 fallback 下一条（转脚本生成 fallback 链）
   - role 概念已向用户解释（ARIA 可访问性角色，get_by_role 稳健但同 role 多元素会冲突）

### 阶段划分（每阶段一个 PR，完成即验收）

| 阶段 | 内容 |
|---|---|
| **1 元素资产** | 元素库拆两页（抓取/管理）；定位器 score 统一（上）；页面树右键编辑/上下移/父子层级(parent_id)；全局共享元素（scope，导航/菜单类跨页引用）；回收站软删30天；引用计数+删除保护（"被N个脚本引用"确认）；快速校验按钮；导入导出 |
| **2 转脚本+测试集** | 转脚本页：页面树(可编辑)+勾选跨页用例+转换弹窗内嵌SSE直播+保存+步骤化脚本编辑器(含 assert_db)；测试集模型+存为测试集；UI自动化测试页：测试集列表/详情/执行(无头有头/失败策略 fail_fast/超时)/SSE直播/报告(截图耗时)/执行记录Tab；**每条失败用例自动存截图+报告内嵌**；**用例可自动化评级**（生成/评审时标记 可自动化/需手工）；转换结果弹窗看代码 |
| **3 回归+菜单+登录态** | 回归自动化页改造（for_regression 数据源/统计卡口径改回归自己的/AI六规则识别保留为辅助建议）；白盒用例归入用例管理；菜单重组（上表）；执行记录与报告并入各页；评审应用建议 LLM 增强（软断言转硬断言等需改写文案的建议真正落地）；登录态复用 |

### 本轮采纳的功能决策明细
- 无头/有头模式：测试集执行配置弹窗 ✅
- 失败截图自动留存+报告内嵌：本轮（阶段2）实现，MinIO 已有基础 ✅
- 用例可自动化评级：阶段2 ✅
- assert_db 数据库断言：阶段2 编辑器加操作类型；用户填 SQL+期望值；AI 可辅助生成 SQL（表结构是平台自己的 SQLAlchemy models）✅
- 定时执行 / 执行并行度 / 通知推送：**二期**（已记录 docs/ROADMAP_PHASE2_TODO.md）
- 回归页 AI 六规则识别：保留为辅助建议（优先级高权重/通过率≥80%高/核心流程中/模块代表性中/稳定性中/依赖低，≥3分纳入），不是独立功能

## 二、千问原型提炼（v6，已全量提炼，重构的 UI 蓝本）

原型文件：`D:\Documents\qwen-agent\VPci6NrZNJ\default\moontest-platform-prototype-20260901T015607383Z\history\v6\delivery\moontest-test-platform.html`

关键设计（已提炼进方案，细节回看原型源码，SECTION 注释定位）：
- elements-list（783-938行）：项目下拉→页面树(250px)→元素表格10列；详情抽屉=定位器列表(★首选/置信度badge/来源/↑↓调序/+自定义定位器)+修改记录timeline+引用脚本清单；回收站；删除保护 confirm
- convert（1102-1234行）：页面树浏览用例+跨页勾选+本次测试集卡片+转换SSE直播(convertLog)+存为测试集
- scripts（1234-1364行）：测试集/脚本库双Tab；测试集详情+执行直播+报告drawer(✅❌⏳+耗时+失败截图MinIO+导出+同步执行记录)；脚本库统计卡5个+列表(分类/状态/受影响黄底/纳入回归)+AI诊断
- regression（1364-1392行）：统计卡4个+AI识别规则alert+脚本表(状态/AI建议/原因/纳入来源)+最近回归报告块
- 数据模型样例：`{id, project, page, scope:"全局|页面级", name, type, status:"有效|疑似失效|已失效|待校验", ref, src, locators:[{t:"id|css|xpath|text|role|自定义", v, score, src}], updated, thumb}`

## 三、本轮已修 bug 清单（全部已验证，多数未提交！）

**⚠️ 工作区有大量未提交改动，下次会话开工前先提交**（建议 2-3 个 commit：bug修复 / 菜单路由 / 日志染色）：

1. **`func` 未定义**（ai_case_tasks.py）：重名去重检查用了 func.count/and_ 没 import → 批量生成全炸。已修 `from sqlalchemy import select, func, and_`
2. **SSE "Event loop is closed"**（core/sse.py）：celery 每任务新事件循环，redis 连接绑旧循环。已修：send_message 捕获 RuntimeError → 重连重试一次（_ensure_redis 检测不可靠，redis-py 跨循环首击必败二次自愈是实测结论）
3. **用例详情 400·步骤缺 step 字段**（test_case_service._to_detail）：AI 生成步骤无 step 序号 → StepSchema 强制 ≥1 炸。已修：序列化时按顺序重编号
4. **应用全部建议无效**（case_refiner + apply_suggestions）：refined_case 只是原样回显，建议无自动落地。已修：缺前置条件时规则层生成默认前置 + apply 时同步到用例。**软断言转硬断言等 LLM 改写类建议的真正落地在阶段3**
5. **schema 200 上限**（schemas/test_case.py）：StepSchema 四字段放宽到 2000；functional_case_generator 截断同步放宽；前端测试数据列超 80 字折叠+展开按钮
6. **`is_deleted == False`**（test_case_service.get_stats）：SQLAlchemy 布尔比较炸 → `is_(False)`
7. **sessions 列表 500**（ai_case_generation.list_sessions）：历史会话 created_at 为 NULL 参与 `>=` 比较炸 → 空值跳过时间过滤
8. **批次用例数显示 0**（case_batch_service.update_case_count）：累加 delta 漂移 → 改实时 COUNT 批内未删用例
9. **批内用例点详情无反应**（CaseDetail.vue）：同组件路由跳转 onMounted 不触发 → watch(route.fullPath) 重载
10. **生成历史用例数 0**（ai-case.js + CaseGenerate.vue）：第6步新造 session_id 没复用识别会话 → generateTestCases 传 currentSessionId
11. **glm-4 → glm-2.5**：全局替换（config/gateway/generators/schemas/tests，32 测试通过）
12. **JSON 围栏解析失败 78/122 条**（core/json_utils.py 新建）：GLM 返回 ```json 围栏 + JSON 后附说明文字（Extra data）。已修 parse_llm_json：剥围栏 + 失败取首个平衡 {...} 块
13. **/ai/convert 空白**（router/index.js）：菜单路径 /ai/convert 无路由 → ScriptConvert 移到 /ai/convert，/scripts 和 /auto/ui 重定向
14. **转脚本 400**：未定稿用例被选 → 前端流程问题（先定稿再转），后端校验正确
15. **日志染色**（core/logging_setup.py）：原 ANSI 转义符丢失显示乱码 `[91m` → 修为真转义，ERROR 红/WARNING 黄（仅控制台）
16. **view_logs.bat 染色**：新建 backend/tail_log_color.ps1（UTF-8 BOM+CRLF），ERROR 红行/WARNING 黄行，view_logs.bat 1/2/3 选项改走染色脚本

**测试基线：全量 541 passed**（最后一次全量跑）

## 四、当前环境状态

- backend：uvicorn `--reload`（PID 变动，8000 端口），改动自动热加载
- celery worker：`python -m celery -A app.tasks worker --pool=solo -l info`（**注意**：正确模块路径是 `-A app.tasks` 不是 `-A app.tasks.celery_app`，后者碰巧能跑但路径不规范）
- redis 队列：purge 命令 `python -m celery -A app.tasks purge -f`（redis-cli 未装）
- 前端：build 产物已更新（最后一次 build 含所有修复）
- view_logs.bat 双开 API/Worker 日志窗口（已带染色）

## 五、下次会话 TODO（按序）

1. **提交工作区**：分 commit 提交上述 16 项修复（当前全在 working tree）
2. **写阶段1实施计划**：`docs/superpowers/plans/2026-09-XX-element-assets.md`（Superpowers writing-plans 流程，TDD bite-sized），核心任务：
   - element_locator 独立表或 locator_strategies 内 score 统一（设计已定稿见上）
   - find() 消费端按 score 降序 + fallback
   - PageRepository 加 parent_id/sort_order（页面树层级+右键编辑/上下移）
   - ElementRepository 加 scope（全局元素，page_id 可空）
   - 软删+回收站（recycled_at）、引用计数（查 script_asset.step_mapping）
   - 快速校验接口（复用登录态 querySelector，命中唯一+10/多个-20）
   - 导入导出
   - 前端：元素列表页（页面树+10列表格+详情抽屉+回收站）、元素抓取页换路由
3. 计划发用户确认 → worktree 隔离 → subagent-driven TDD 执行
4. 阶段1验收后依次推进阶段2、3

## 六、关键约定（不变）

- Superpowers 流程：brainstorm→plan→TDD→编码→审查；不主动写总结报告
- commit 前必须只 stage 指定文件（历史教训：同仓多会话提交混入 4b1bca7）
- mock 测试掩盖 Critical 的教训：阶段验收必须真浏览器/真 DB 守门测试
- 用户偏好：先方案后动工、每阶段验收、中文沟通、一期先跑通流程（定时/并行/通知均二期）
