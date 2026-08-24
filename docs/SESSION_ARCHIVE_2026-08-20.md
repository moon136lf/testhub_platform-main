# Session Archive — P0 缺口补全 brainstorming（AI生成 + 用例管理）

**存档日期**：2026-08-20
**会话焦点**：用 `superpowers:brainstorming` 为 AI用例生成(#2) + 用例管理(#3) 两模块补全 P0 缺口（元素库 #1 跳过，正在开发）。缺口来源 `docs/GAP_ANALYSIS_2026-08-20.md`。
**当前阶段**：brainstorming 设计推进到 W6，卡在 2 个待确认问题。确认后写 spec → self-review → 用户评审 → writing-plans。

---

## 1. 已锁定的设计决策（全部经用户确认）

### 全局决策
- 元素库 #1 跳过（正在开发），本会话只做 #2 AI生成 + #3 用例管理
- P0 范围 = **全量**，含版本历史 / 导入导出 / 评审精修 5 字段
- 用 superpowers 流程：brainstorm → writing-plans → TDD → 编码 → verification

### W2 数据契约统一
- 步骤结构统一为 `{step, action, target, data, expected}`
- 枚举英文 slug 存库 + 前端中文映射：
  - `case_type`: `functional` / `interface_case`（功能用例/接口用例）
  - `automation_status`: `pending` / `automated` / `partial_automated`（未转化/已自动化/部分自动化）
  - `review_status`: `pending` / `passed` / `needs_revision`
  - `feasibility_level`: `full` / `partial` / `manual`
- 旧枚举值归并：`performance/security/compatibility/usability → functional`；`api → interface_case`；`cannot_automate → partial_automated`
- 步骤 JSON 键 `seq → step`，列类型 `JSON → JSONB`
- `TestCase` 加 `UniqueConstraint(project_id, name)` + 索引 `idx_test_case_project` / `idx_test_case_automation`
- 幂等迁移脚本 `backend/migrations/align_test_case_schema.sql`

### W1 Bug 修复
- `ai_case_generation.py:345-350` 移除 `TestPoint.is_deleted.is_(False)` 过滤（列不存在）
- `Cases.vue:396-400` 批量定稿 `action:'update_status'` → `action:'finalize'`，去掉 `update_data`

### W3 版本历史
- 新表 `CaseVersion`：id/case_id/version/snapshot(JSONB)/diff_summary/changed_by/created_at + idx
- 快照记录**变更前**数据，version 每次 update +1
- 回滚：用 snapshot 覆盖，version **不回退、继续递增**，回滚动作本身再写一条快照
- API：GET versions / GET version detail / POST rollback
- 前端 CaseDetail.vue 加版本历史折叠面板
- 迁移 `add_case_version_table.sql`

### W4 导入导出
- 导出格式 `.xlsx` / `.json` / `.xmind`（**xmind 加 `xmind` 依赖**，真实 XMind 8 格式）
- 导入格式 `.xlsx` / `.csv` / `.md`
- 名称冲突 → **跳过**（保护现有数据），记入 errors
- 返回 `{imported, failed, errors:[{row, reason}]}`
- API：GET export / POST import；前端 Cases.vue 加导入/导出按钮

### W5 用例评审 + E2E 精修引擎（P0 全量）
- **精修目标**：转脚本前把用例质量拉满
- **精修改「规则 + LLM 混合」**：规则层免费先跑（永真断言黑名单、动作动词校验、模糊预期识别、步骤完整性 checklist、重复用例比对），LLM 层补语义（异常路径、软→硬断言改写、可行性综合判定）
- **5 个精修维度**：步骤完整性 / 断言增强 / 异常路径补充 / 数据准备清理 / 可行性修正
- 精修引擎 `services/case_refiner.py`，输入用例+页面元素清单(元素库降级跳过)+规则库，输出精修后用例+报告
- 精修**同步版**（阻塞等 LLM 返回，规则层零 token 先跑），异步 SSE 留 P1
- 报告 `refinement_report` JSONB **同时存精修后用例**，前端做 diff 视图
- 评审流转：pending → passed/needs_revision；精修完成 → `is_finalized=true`
- `feasibility_level` + `cannot_automate_reason` 由精修引擎维度5自动填
- API：POST refine / GET refinement-report / POST apply-suggestions / PATCH review
- 新增字段：review_status / review_comment / feasibility_level / cannot_automate_reason / refinement_report / refined_at
- 迁移 `add_review_refinement_fields.sql`

### Skill 规则边界划分
- **精修模块(#3 W5)参考用例层**：永真断言黑名单+思想实验自检、预期→断言映射、步骤动作映射、质量自检 #2/#5/#8
- **转脚本模块(#4)参考脚本层**：定位策略优先级、禁索引、等待策略、禁编造DOM、调试三轮、失败归因四分类、知识库回写、工程结构、质量自检 #1/#3/#4/#6/#7
- skill 原文归档 `docs/skills-reference/testcase-to-script-skill.md`，记忆 `testcase-to-script-skill.md`

---

## 2. W6 设计（AI生成前端重写 + 后端对齐，已呈现待确认）

- 前端 CaseGenerate.vue 全量重写为需求 7 步：选项目→上传/输入材料(3源+文本,聚合校验至少一种,≤10MB)→4规则开关(automation_thinking强制,边界值,场景法,等价类)→AI识别+文字直播SSE→测试点按page_name分组勾选+类型筛选→生成用例→结果预览+幻觉标记列
- 后端：4规则开关传递(IdentifyPointsRequest加rules dict)、禁用词注入(test_case_generator prompt去verify,注入禁用词)、Token真实值累计(ai_gateway返回tokens累加推送)、SSE stage收敛、type_label改5枚举、TestPoint.status枚举对齐

### 待确认 2 个问题（W6 收尾）
1. **SSE stage**：需求 §6.1 明确 stage 枚举 4 值(parse_doc/identify_point/generate_case/detect_hallucination)。建议 stage 收敛 4 个(知识库检索等子步骤归入identify_point) + content 文本保留全量细粒度。→ **待用户确认**
2. **Token 预估**：tokens_used 推实际累计，tokens_estimated_total 用「点数×单条预估」粗估 还是 暂留空？→ **待用户确认**

---

## 3. 关键文件位置

### 已产出
- 缺口清单：`docs/GAP_ANALYSIS_2026-08-20.md`
- 会话交接：`docs/SESSION_HANDOFF_2026-08-20.md`
- 需求分节：`docs/requirements_sec_*.md`（3.1/3.4/3.5/8.2/8.3/9/10/11；§3.2未单独切，在 requirements_extracted.md 596-739行）
- skill 归档：`docs/skills-reference/testcase-to-script-skill.md`
- 记忆：`C:\Users\moon1\.claude\projects\D--MoonTest\memory\`（moontest-project/gap-analysis/superpowers-workflow/testcase-to-script-skill + MEMORY.md）

### 待产出
- spec 文档：`docs/superpowers/specs/2026-08-20-p0-gap-fill-design.md`（W6 确认后写）

### 代码落点
- 后端 model：`backend/app/models/test_case.py`（加评审字段）、新 CaseVersion
- 后端 service：`backend/app/services/`（新 case_refiner.py、import_export_service.py）
- 后端 API：`backend/app/api/v1/test_cases.py`、`ai_case_generation.py`
- 后端迁移：`backend/migrations/`（align_test_case_schema.sql / add_case_version_table.sql / add_review_refinement_fields.sql）
- 前端：`frontend/src/views/Cases.vue`、`CaseDetail.vue`、`components/testCase/*`、`views/ai/CaseGenerate.vue`、`api/ai-case.js`

### checkpoint 发现的风险
- **代码库非 git 跟踪**（git status 全 untracked，仅 1 commit 7572e07），无法 git 回滚 → spec/计划落盘后手动备份
- **/ai/review 菜单死链**：MainLayout.vue:32 有菜单项，router 无 `/ai/review` 路由 → spec 落地时补
- W1-W5 设计此前只在 transcript，本次存档已固化

---

## 4. 如何在新会话继续

把本存档贴给新会话，附：
> 续 P0 缺口补全 brainstorming。W1-W6 设计已固化在 `docs/SESSION_ARCHIVE_2026-08-20.md`。先确认 W6 两个问题：(1) SSE stage 收敛4值+content保留全量细粒度；(2) Token 预估用粗估还是暂留空。确认后写 spec 到 `docs/superpowers/specs/2026-08-20-p0-gap-fill-design.md`，self-review，用户评审，再 invoke writing-plans。
