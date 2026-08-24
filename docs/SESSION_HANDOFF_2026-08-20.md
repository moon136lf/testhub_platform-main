# MoonTest 上下文存档与会话交接

**创建时间**：2026-08-20
**目的**：供在新会话窗口中继续本任务使用。包含：项目现状、已完成模块、当前任务、待办、关键文件位置、如何继续。

---

## 1. 项目现状一句话

MoonTest 是一个测试平台（Python FastAPI + Celery + Playwright 后端 / Vue3 + Element Plus 前端），采用 Superpowers 工程流程（brainstorm → plan → TDD → 编码 → 审查 → 验收）开发。需求文档在 `docs/design-doc-raw.xml`（Word 导出的 XML，已抽取纯文本到 `docs/requirements_extracted.md` 及分节文件 `docs/requirements_sec_*.md`）。

---

## 2. 全期 11 个模块进度（来自 `.claude/TODO_LIST.md`）

| # | 模块 | 状态 | 设计/计划文档 |
|---|---|---|---|
| 1 | 元素库 | ✅ 代码完成（有缺口）| `.claude/plans/element-library-design.md` + `docs/superpowers/plans/2026-08-18-element-library-implementation.md` |
| 2 | AI智能用例生成 | ✅ 代码完成（有缺口）| `docs/superpowers/specs/2026-08-18-ai-case-generation-design.md` + `docs/superpowers/plans/2026-08-18-ai-case-generation.md` |
| 3 | 用例管理 | ✅ 代码完成（有缺口）| `docs/superpowers/specs/2026-08-18-case-management-design.md` + `docs/superpowers/plans/2026-08-18-case-management.md` |
| 4 | 用例转自动化脚本 | ⬜ 未开始 | — |
| 5 | UI自动化测试执行 | ⬜ 未开始 | — |
| 6 | 执行记录与报告 | ⬜ 未开始 | — |
| 7 | 用例评审与E2E精修 | ⬜ 未开始（需求 §3.2 标 P0）| — |
| 8 | 回归测试 | ⬜ 未开始 | — |
| 9 | 白盒代码体检 | ⬜ 未开始 | — |
| 10 | 系统设置 | ⬜ 未开始 | — |
| 11 | 仪表盘优化 | ⬜ 未开始 | — |

---

## 3. 最近完成的事：需求文档对照审查

### 用户原话要求
> "查看我之前完成的部分和需求文档对比，是否缺失需求文档的内容，查看我完成的每一个模块需求文档中的页面结构、字段定义、业务逻辑以及第二部分详细设计文档相关内容是否与现有代码吻合，输出缺失部分"

### 产出文档
**`docs/GAP_ANALYSIS_2026-08-20.md`** — 三个已完成模块（元素库 / AI生成 / 用例管理）对照需求文档的全部缺失/不符项，已逐条核实代码。

### 审查方法
- 用 Python 从 `design-doc-raw.xml` 抽取纯文本到 `docs/requirements_extracted.md`（5331 段）
- 按章节切成 8 个小文件 `docs/requirements_sec_*.md`（3.1/3.4/3.5/8.2/8.3/9/10/11）便于子代理按需读取
- 派发 3 个并行 Explore 子代理逐文件对比，再用 Grep 直接核实关键 bug

### 三大阻断性 Bug（P0，必须先修）
1. **元素库 `batch_import_elements` 字段映射损坏** — `backend/app/services/element_service.py:105-117` 仍用 `alias/display_text/coord_x/coord_y/locator_chain`，model 改名后未同步，源码已 TODO 标注 BROKEN。**当前一键入库必失败。**
2. **`TestPoint.is_deleted` 查询 bug** — `backend/app/api/v1/ai_case_generation.py:348` 引用不存在的列。
3. **用例管理前端批量定稿 action 名错** — `frontend/src/views/Cases.vue:397-399` 调 `action:'update_status'`，后端只认 `finalize`。

### 每模块缺失概要（详见 GAP_ANALYSIS 文档）

**元素库**：变更检测全缺（ELEM-04/05/06/07）、自愈缓存全缺（self_heal_cache 表/置信度衰减/降级执行器）、三类 Redis 键全缺、前端缺截图高亮/抓取历史/变更检测区、入库弹窗不完整、多个 DDL 不符（丢唯一约束、置信度注释错、变更检测缺聚合字段）。

**AI生成**：前端缺文字直播 SSE 订阅与 7 步结构、4 规则开关缺失、CASE-04 禁用词未注入 prompt、Token 成本管理整体缺失（token_usage/quota 表 + /tokens/status）、幻觉检测缺 PRD 语义比对与复核定稿、SSE stage 枚举未收敛为 4 值、Token 实时推送恒 0、type_label/状态枚举不符。

**用例管理**：版本历史与回滚全缺、导入导出全缺、用例评审 5 字段全缺（review_status/review_comment/feasibility_level/cannot_automate_reason/refinement_report）、自动化状态自动流转缺、前后端字段/枚举/步骤结构多处不一致、test_case 缺 UNIQUE 约束与索引、steps 用 JSON 非 JSONB。

### 跨模块共性缺失
- Redis 缓存键体系（§8.3）
- Token 成本管理（§11.4）
- 自愈引擎（§11.1/§8.2.8）
- SSE stage 统一 + 断线重连 + last_event_id 续传（§6.1/§11.3）
- 字段/枚举前后端全栈统一

---

## 4. 补全优先级总表（建议执行顺序）

### P0（阻断主流程 / 必修 Bug）
1. 修复元素库 `batch_import_elements` 字段映射
2. 修复 `TestPoint.is_deleted` 查询 bug
3. 修复用例管理前端批量定稿 action 名
4. 前后端字段/枚举/步骤结构全栈统一（三模块）
5. AI生成前端补文字直播 SSE + 7 步结构
6. AI生成 4 规则开关 + CASE-04 禁用词 prompt 注入
7. AI生成 Token 实时推送真实值

### P1（功能完整性）
8. 元素库 self_heal_cache model + 迁移 + 三类 Redis 键
9. 元素库变更检测聚合字段 + ELEM-05/06/07
10. AI生成 token_usage/quota + `GET /tokens/status`
11. AI生成 幻觉 PRD 语义比对 + 复核定稿 + detect_hallucination 独立 stage
12. 用例管理 版本历史 + 导入导出
13. 用例管理 用例评审 5 字段（§3.2）
14. DDL 对齐：UNIQUE 约束 + 索引 + steps JSONB
15. 前端补：元素库截图高亮/抓取历史/变更检测区；用例管理版本历史面板/批量操作入口

---

## 5. 关键文件位置速查

### 需求文档
- 原始：`docs/design-doc-raw.xml`（Word XML，3.4MB）
- 纯文本抽取：`docs/requirements_extracted.md`
- 分节：`docs/requirements_sec_3.1_ai_case_generation.md` / `_3.4_case_management.md` / `_3.5_element_library.md` / `_8.2_ddl.md` / `_8.3_redis.md` / `_9_api.md` / `_10_flows.md` / `_11_detail_design.md`

### 后端代码
```
backend/app/
  models/   element.py, test_case.py, generation.py, execution.py, knowledge.py, project.py, test_rule.py
  services/ element_service.py, playwright_service.py, test_case_service.py,
            ai_gateway.py, document_parser.py, test_point_generator.py, test_case_generator.py,
            hallucination_detector.py, knowledge_service.py
  api/v1/   elements.py, ai_case_generation.py, test_cases.py, sse.py, projects.py, health.py
  tasks/    element_tasks.py, ai_case_tasks.py
  core/     database.py, redis.py, sse.py, storage.py, config.py
backend/migrations/  extend_element_tables.sql, add_ai_case_generation_tables.sql
backend/tests/  test_storage.py, test_ai_gateway.py, test_document_parser.py,
                test_knowledge_service.py, test_api_ai_case_generation.py,
                test_test_case_api.py, test_test_case_service.py
```

### 前端代码
```
frontend/src/
  views/  ElementLibrary.vue, Cases.vue, CaseDetail.vue, Dashboard.vue, ProjectManagement.vue,
          ai/CaseGenerate.vue, ai/GenerationHistory.vue, ai/KnowledgeManagement.vue, ai/RuleManagement.vue
  components/testCase/  CaseFilter.vue, CaseForm.vue, CaseStepEditor.vue
  api/    element.js, ai-case.js, testCase.js, project.js, axios.js
  router/index.js  (路由：/dashboard /projects /ai/generate /ai/knowledge /ai/rules /ai/history /elements /cases /cases/:id)
```

### 设计/计划文档
- 元素库：`.claude/plans/element-library-design.md`（设计）+ `docs/superpowers/plans/2026-08-18-element-library-implementation.md`（10任务计划，未执行）
- AI生成：`docs/superpowers/specs/2026-08-18-ai-case-generation-design.md` + `docs/superpowers/plans/2026-08-18-ai-case-generation.md`
- 用例管理：`docs/superpowers/specs/2026-08-18-case-management-design.md` + `docs/superpowers/plans/2026-08-18-case-management.md`

### 其他报告
- `COMPLETION_REPORT.md`（元素库完成报告）
- `backend/TASK9_IMPLEMENTATION_REPORT.md`（元素库 model 扩展报告，含 BROKEN 标注）
- `.claude/TODO_LIST.md`（11 模块进度清单）

---

## 6. 如何在新会话继续

### 选项 A：补全缺口（推荐）
直接把本文件和 `docs/GAP_ANALYSIS_2026-08-20.md` 的内容贴给新会话，说：
> "对照 docs/GAP_ANALYSIS_2026-08-20.md 的 P0 清单，按顺序修复 7 个阻断项。每修一个跑测试验证。"

### 选项 B：执行元素库计划
若要先执行之前写的元素库 10 任务实施计划：
```
/superpowers:subagent-driven-development D:/MoonTest/docs/superpowers/plans/2026-08-18-element-library-implementation.md
```
但注意：该计划未覆盖 GAP_ANALYSIS 里发现的字段映射 bug、变更检测、自愈缓存、Redis 键等缺口，建议先按选项 A 修 P0 再考虑。

### 选项 C：重新做需求对照
把用户原话要求贴给新会话即可复现本次审查：
> "查看已完成模块和需求文档 docs/design-doc-raw.xml 对比，逐模块核对页面结构/字段定义/业务逻辑/第二部分详细设计是否吻合，输出缺失部分。需求文档已抽取到 docs/requirements_sec_*.md。"

---

## 7. 环境与运行

- 后端：`cd backend && pip install -r requirements.txt && playwright install chromium`，PostgreSQL + Redis + MinIO
- 启动：`celery -A app.tasks worker --loglevel=info --pool=solo` + `uvicorn app.main:app --reload`
- 前端：`cd frontend && npm install && npm run dev` → http://localhost:5173
- 测试：`cd backend && pytest`
- 迁移未执行（无 DB 连接）：`psql -U <user> -d <db> -f backend/migrations/extend_element_tables.sql`
- 非 git 仓库（无法提交，需手动 git init 或手动备份）
