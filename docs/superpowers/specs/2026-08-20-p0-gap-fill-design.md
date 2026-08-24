# P0 缺口补全设计 — AI用例生成 + 用例管理

**版本**：v1.0
**日期**：2026-08-20
**作者**：Claude Code (Opus 4.8)
**状态**：待审批
**流程**：Superpowers（brainstorming → writing-plans → TDD → 编码 → verification）
**范围依据**：`docs/GAP_ANALYSIS_2026-08-20.md` P0 清单

---

## 1. 概述

补全 AI智能用例生成(#2) + 用例管理(#3) 两模块的 P0 缺口。元素库(#1) 正在开发，跳过；评审精修(#7) 字段提前到本次实现（需求 §3.2 标 P0）。

### 1.1 目标

对照需求文档 `docs/requirements_sec_*.md`，修复 3 个阻断性 bug，统一数据契约，补齐版本历史、导入导出、用例评审+E2E精修引擎、AI生成前端 7 步 SSE 重写。

### 1.2 P0 范围与工作块

| # | 工作块 | 模块 | 性质 | 依赖 |
|---|---|---|---|---|
| W1 | Bug 修复（is_deleted、批量定稿 action） | AI生成+用例管理 | 修复 | 无 |
| W2 | 枚举/步骤结构/字段名全栈统一 + 幂等迁移 | 用例管理 | 对齐 | 无（先行）|
| W3 | 用例版本历史（case_version + diff + 回滚） | 用例管理 | 新功能 | W2 |
| W4 | 用例导入导出 | 用例管理 | 新功能 | W2 |
| W5 | 用例评审 5 字段 + E2E 精修引擎 | 用例管理 | 新功能 | W2（元素库降级）|
| W6 | AI生成前端 7 步 SSE 重写 + 后端规则对齐 | AI生成 | 重写 | 无 |

执行顺序：W2 → W1 → W3 → W4 → W5 → W6。

### 1.3 全局决策（已确认）

- 步骤结构统一为 `{step, action, target, data, expected}`
- 枚举英文 slug 存库 + 前端中文映射
- 幂等迁移脚本（沿用 `extend_element_tables.sql` 风格），无 DB 连接时备好手动跑
- AI生成前端全量重写 7 步 + SSE 订阅 + 4 规则开关
- P0 全量：含版本历史 / 导入导出 / 评审精修 5 字段
- xmind 导出加 `xmind` 依赖（真实 XMind 8 格式）
- 导入名称冲突 → 跳过（保护现有数据）
- 精修 P0 全量做；元素库可用则用、不可用降级跳过
- 精修改「规则 + LLM 混合」（规则免费先跑，LLM 补语义）
- 精修同步版（阻塞等 LLM 返回，规则层零 token），异步 SSE 留 P1
- SSE stage 收敛 4 值，content 保留全量细粒度
- Token 预估用粗估（点数 × 单条预估），满足 CASE-08

---

## 2. W2 数据契约统一 + 迁移

### 2.1 枚举规范化

| 字段 | 需求中文 | 后端 slug | 前端映射 |
|---|---|---|---|
| `case_type` | 功能用例/接口用例 | `functional`/`interface_case` | 功能用例/接口用例 |
| `automation_status` | 未转化/已自动化/部分自动化 | `pending`/`automated`/`partial_automated` | 同 |
| `review_status` | 待评审/已通过/需修改 | `pending`/`passed`/`needs_revision` | 同 |
| `feasibility_level` | 完全自动化/部分自动化/需手工执行 | `full`/`partial`/`manual` | 同 |
| `hallucination_status` | 正常/疑似幻觉/已确认 | `normal`/`suspected`/`confirmed` | 不变 |

枚举常量集中在 `schemas/test_case.py` 顶部（如 `CASE_TYPES`、`AUTOMATION_STATUSES`），schema pattern 和前端映射引用同一来源。

### 2.2 步骤结构统一

- 后端 `StepSchema`：`seq` → `step`，保留 `action/target/data/expected`，长度上限 action≤200, expected≤200, target≤200, data≤200
- 前端 `CaseStepEditor`：`step_number` → `step`
- 现有 `seq` 键由迁移脚本改 `step`

### 2.3 model 调整（`models/test_case.py`）

- `steps` 改 `JSONB`
- `TestCase.__table_args__`：`UniqueConstraint(project_id, name)` + `Index(idx_test_case_project)` + `Index(idx_test_case_automation)`
- W2 阶段不加评审字段和 case_version 表（W3/W5 各自独立加）

### 2.4 迁移 `backend/migrations/align_test_case_schema.sql`（idempotent）

1. case_type 规范化：performance/security/compatibility/usability → functional；api → interface_case
2. automation_status 规范化：cannot_automate → partial_automated；automated/pending 保留
3. steps JSON 键 seq → step（PostgreSQL jsonb 遍历更新）
4. steps 列类型 JSON → JSONB（USING steps::jsonb）
5. 去 UNIQUE 冲突后加 UNIQUE(project_id, name)
6. 加索引 IF NOT EXISTS

### 2.5 测试

`tests/test_test_case_schema_alignment.py`：枚举常量唯一、StepSchema 字段名/长度、拒绝旧枚举值接受新值、UniqueConstraint 声明。

---

## 3. W1 Bug 修复

### 3.1 TestPoint.is_deleted 查询 bug

- 位置 `api/v1/ai_case_generation.py:345-350`
- 修法：移除 `TestPoint.is_deleted.is_(False)`（TestPoint 物理删除无软删）
- 全文件 grep is_deleted 确认无其他误引用

### 3.2 前端批量定稿 action

- 位置 `frontend/src/views/Cases.vue:396-400`
- 修法：`action:'update_status'` → `action:'finalize'`，去掉 update_data

### 3.3 测试

`tests/test_ai_bugfix.py`：get_test_points 不再引用 is_deleted；批量 finalize action 名正确。

---

## 4. W3 用例版本历史

**需求**：CASE-MGMT-02「每次修改记录版本历史（diff），支持回滚」。

### 4.1 数据模型 `CaseVersion`（加到 `models/test_case.py`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| case_id | UUID FK→test_case CASCADE | |
| version | Integer | 版本号（与用例当时 version 一致）|
| snapshot | JSONB | 用例变更前完整快照（可变字段）|
| diff_summary | Text | 与上一版变化字段摘要 |
| changed_by | String(50) | 修改人 |
| created_at | DateTime | 快照时间 |
| 索引 | idx_case_version_case | |

### 4.2 业务逻辑（`test_case_service.py`）

- 快照时机：用例每次 update（非 finalize 批量操作）成功后，写 CaseVersion：snapshot=变更前数据，version=变更前 version，diff_summary=变化字段列表
- version 自增：每次 update version += 1
- 回滚 `rollback_case(case_id, target_version)`：用 snapshot 覆盖当前可变字段，version 取 max+1（不回退），再写一条快照记录回滚动作

### 4.3 API

| 方法 | 路径 |
|---|---|
| GET | `/test-cases/{case_id}/versions` |
| GET | `/test-cases/{case_id}/versions/{version}` |
| POST | `/test-cases/{case_id}/rollback?version=N` |

### 4.4 前端（`CaseDetail.vue`）

版本历史折叠面板：时间线展示 v1.0/v1.1…，每条 version/时间/修改人/diff_summary + 「回滚到此版本」按钮。

### 4.5 迁移 `add_case_version_table.sql`（idempotent）

CREATE TABLE IF NOT EXISTS + 索引。

### 4.6 测试

`tests/test_case_version.py`：update 生成快照+version自增、快照内容正确、回滚恢复+version递增+回滚动作有快照、快照失败不阻塞主更新。

---

## 5. W4 用例导入导出

**需求**：CASE-MGMT-03「导入 .xlsx/.csv/.md；导出 .xlsx/.json/.xmind」。

### 5.1 服务 `import_export_service.py`（新建）

依赖：openpyxl（已装）、xmind（新增，真实 XMind 8 格式）、csv/json 标准库。

| 方法 | 说明 |
|---|---|
| export_cases(project_id, fmt) | xlsx 每用例一块步骤展开多行 / json 用例数组 / xmind 项目-模块-用例树 |
| import_cases(project_id, file_bytes, fmt) | xlsx 反解 / csv 列解析 / md 按标题分块 |

导入校验：复用 CaseCreateRequest 逐条校验，失败收集到 errors 不中断；名称冲突跳过记入 errors。返回 `{imported, failed, errors:[{row, reason}]}`。

### 5.2 API

| 方法 | 路径 |
|---|---|
| GET | `/test-cases/export?project_id=&format=xlsx|json|xmind` |
| POST | `/test-cases/import`（multipart + project_id）|

### 5.3 前端（`Cases.vue`）

工具栏加「导入」「导出」按钮。导出下拉选格式直接下载；导入弹窗选文件+预览校验结果+确认上传。

### 5.4 测试

`tests/test_import_export.py`：三种导出生成非空正确文件、csv 导入正确创建+冲突跳过+非法行进 errors、round-trip 一致（可接受 id/时间差异）。

---

## 6. W5 用例评审 + E2E 精修引擎

**需求**：§3.2 用例评审与E2E精修（P0）。完整评审流程页和 E2E 报告生成属 #7 模块，本次做字段+精修引擎+基础流转。

> 优先级偏差说明：设计文档 §14 曾把评审划二期，但需求 §3.2 是 P0，本次提前到一期。

### 6.1 精修逻辑（需求 REVIEW-03 / §3.2 技术方案）

**目标**：转脚本之前把用例质量拉满。
**输入**：用例 + 页面元素清单（元素库降级时缺省）+ 精修规则库
**输出**：精修后用例 + 精修报告

**5 个精修维度**：

| 维度 | 做什么 | 实现（规则/LLM）|
|---|---|---|
| 步骤完整性 | 补全缺失步骤 | 规则：动作动词校验 + checklist |
| 断言增强 | 软断言转硬断言 | 规则：永真断言黑名单扫描 + LLM 改写建议 |
| 异常路径补充 | 主流程补异常分支 | LLM：补密码错误/超时/空值 |
| 数据准备/清理 | 补前置数据与后置清理 | 规则：检查 setup/teardown 步骤 |
| 可行性修正 | 剥离不可执行部分 | 规则：观察/视觉类步骤 → manual + reason |

**混合架构**：规则层免费零 token 先跑，LLM 层补语义（缓解 P0 Token 成本缺口，报告更稳定可解释）。

**精修报告 `refinement_report` JSONB 结构**：
```json
{
  "score": 82,
  "refined_case": {...},
  "suggestions": [
    {"id":"S1","dimension":"断言增强","severity":"high","target_step":2,"issue":"...","suggestion":"...","status":"pending"}
  ],
  "normativity": {"steps_complete":true,"assertion_executable":false,"precondition_complete":true},
  "reuse_level": "new"
}
```

报告同时存精修后用例，前端做 diff 视图。

### 6.2 精修引擎 `services/case_refiner.py`（新建）

```
CaseRefiner.refine(case, page_elements=None) → refinement_report
├── _check_steps_completeness(case)      # 维度1 规则
├── _enhance_assertions(case, elements)  # 维度2 规则+LLM
├── _suggest_exception_paths(case)       # 维度3 LLM
├── _check_data_setup(case)             # 维度4 规则
├── _assess_feasibility(case, elements) # 维度5 规则 → feasibility_level + cannot_automate_reason
├── _check_reuse(case, knowledge)       # 复用度（知识库降级跳过）
└── _calculate_score(各维度结果)         # 评分 0-100
```

规则常量：`FORBIDDEN_TAUTOLOGICAL_ASSERTIONS`（永真断言黑名单）、`ACTION_VERB_MAP`（步骤动作映射→可执行性+是否需断言）、`AMBIGUOUS_EXPECTED`（模糊预期列表）。参考 `docs/skills-reference/testcase-to-script-skill.md` 用例层规则。

### 6.3 评审流转（REVIEW-01/05）

```
pending ──评审──► passed ──精修完成──► is_finalized=true
       └─needs_revision ──修改──► 重新评审(回 pending)
```

feasibility_level 由精修引擎维度5自动判定（REVIEW-02）。精修后 is_finalized=true（REVIEW-05）。

### 6.4 字段（加到 TestCase）

| 字段 | 类型 | 默认 |
|---|---|---|
| review_status | String(20) | pending |
| review_comment | Text | null |
| feasibility_level | String(20) | null |
| cannot_automate_reason | String(200) | null |
| refinement_report | JSONB | null |
| refined_at | DateTime | null |

### 6.5 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/test-cases/{case_id}/refine` | 触发精修（同步），返回报告 |
| GET | `/test-cases/{case_id}/refinement-report` | 取最新报告 |
| POST | `/test-cases/{case_id}/apply-suggestions` | 应用建议（全部或指定 id）|
| PATCH | `/test-cases/{case_id}/review` | 更新评审状态/意见 |

### 6.6 前端

- Cases.vue：加评审状态/精修评分列+筛选；批量菜单加「批量评审」
- CaseDetail.vue：评审区 + 精修报告区（评分+建议列表逐条确认/拒绝+一键应用全部+规范度/复用度）+ 精修前后 diff + 「触发精修」按钮

### 6.7 迁移 `add_review_refinement_fields.sql`（idempotent）

6 列 ADD COLUMN IF NOT EXISTS，review_status DEFAULT 'pending'。

### 6.8 测试

`tests/test_case_refiner.py`：软断言→维度2建议、缺前置→维度4标记、可视化步骤→维度5 manual+reason、元素清单空→维度2/5 skipped 报告仍完整、评分 0-100、应用建议后字段正确更新。

---

## 7. W6 AI生成前端重写 + 后端规则对齐

**需求**：§3.1 七步、§6.1 SSE、CASE-04 禁用词、CASE-08 Token。

### 7.1 前端 CaseGenerate.vue 全量重写（7 步）

| 步 | 内容 | 控件 |
|---|---|---|
| 1 | 选择项目 | el-select |
| 2 | 上传/输入材料 | PRD文档/设计方案/UI原型 3 上传 + 需求文本框；聚合校验"至少一种"；≤10MB 前端校验 |
| 3 | 选择生成规则 | 4 个 el-switch：自动化思维规则(强制不可关)、边界值分析、场景法覆盖、等价类划分 |
| 4 | AI识别测试点 + 文字直播 | 按钮→EventSource 订阅 SSE；文字直播区+进度条 |
| 5 | 测试点勾选 | 按 page_name 分组；全选/反选；类型筛选下拉（正常/异常/边界值/等价类/场景法）|
| 6 | 生成所选用例 | 按钮→SSE 继续推送 |
| 7 | 结果预览 + 幻觉标记 | 用例列表 + hallucination_status 列 + ⚠️ 样式；疑似幻觉橙色背景 |

### 7.2 SSE 订阅（`api/ai-case.js` 加 `subscribeSSE`）

EventSource('/api/sse/stream/'+sessionId)，onmessage 解析 7 字段，更新直播区/进度条/Token 计数。

### 7.3 后端规则对齐

**a. 4 规则开关**：IdentifyPointsRequest 加 `rules: {automation_thinking, boundary_value, scenario_analysis, equivalence_partition}`（automation_thinking 强制 true）；task 接收动态构建 rules 列表；TestPointGenerator.generate 按 switch 注入 prompt。

**b. 禁用词注入（CASE-04）**：test_case_generator.py prompt action 候选去 verify，改 navigate/click/input/select/check/assert/wait；注入禁用词清单（观察/验证/查看/确认），强制动作动词为点击/填充/断言。test_point_generator.py type_label 改 5 枚举（正常流程/异常流程/边界值/等价类/场景法）。

**c. Token 真实值（CASE-08）**：ai_gateway.chat 已返回 tokens，task 维护 total_tokens 累计器，每次调用后累加；send_message 传 tokens_used=total_tokens、tokens_estimated_total=点数×单条预估（粗估）。

**d. SSE stage 收敛 4 值**：parse_doc/identify_point/generate_case/detect_hallucination。fetch_knowledge/apply_rules/load_knowledge/save_points 归入 identify_point（靠 content 展示细粒度）。每条生成后幻觉检测新增 detect_hallucination stage 推送。

### 7.4 测试点状态枚举对齐

> 注：此处改的是 TestPoint.**status** 列（业务状态枚举），与 W1 §3.1 删除的 TestPoint.**is_deleted** 列无关——TestPoint 无软删除，走物理删除。

TestPoint.status：pending/approved/rejected → pending/selected/generated（待勾选/已勾选/已生成用例），迁移 `align_test_point_status.sql` 一并处理。

### 7.5 测试

`tests/test_ai_case_rules.py`：rules 4 开关 automation_thinking 强制 true、禁用词出现在 steps 视为缺陷（mock）、type_label 5 枚举校验。
`tests/test_ai_sse_stages.py`：stage 只在 4 合法值、detect_hallucination 独立推送、tokens_used 累加非 0。

---

## 8. 迁移脚本汇总

| 脚本 | 块 | 内容 |
|---|---|---|
| align_test_case_schema.sql | W2 | 枚举规范化+steps JSONB+UNIQUE+索引+步骤键名 |
| add_case_version_table.sql | W3 | case_version 表+索引 |
| add_review_refinement_fields.sql | W5 | 6 评审字段 |
| align_test_point_status.sql | W6 | test_point.status 枚举 |

全部 idempotent，无 DB 连接时手动跑。

---

## 9. 依赖更新

`backend/requirements.txt` 加 `xmind`（W4 真实 XMind 8 导出）。

---

## 10. 风险与边界

- **代码库非 git 跟踪**：无法 git 回滚，spec/计划落盘后手动备份
- **/ai/review 菜单死链**：MainLayout.vue:32 有菜单，router 无 /ai/review 路由 → 本 spec 不建独立评审页（评审嵌入 Cases/CaseDetail），如需独立页 P1 补路由
- **元素库依赖**：精修查元素库降级跳过，元素库完成后自动生效
- **精修同步阻塞**：LLM 调用有耗时，同步有 HTTP 超时风险，超时由前端 loading 提示，异步留 P1
- **不涉及**：失败归因四分类/调试三轮/工程结构等脚本层规则留 #4 转脚本模块

---

**待审批。**

---

## Self-Review 记录（2026-08-20）

| 项 | 结果 |
|---|---|
| 占位符扫描 | 无 TBD/TODO（代码里已有的 BROKEN TODO 是被修复对象，非 spec 占位）|
| 内部一致性 | 枚举值全文统一；W2/W3/W5 迁移脚本独立无交叉；execution order W2→W1→W3→W4→W5→W6 各块依赖清晰 |
| 范围检查 | 单一 spec 可承载，6 工作块边界明确，不超 4 周 |
| 歧义检查 | 已澄清：精修同步版、报告存精修后用例、stage 收敛 4 值+content 全量、Token 粗估；补充 TestPoint.status（业务枚举）≠ is_deleted（删除标记）区分 |

确认后转入 writing-plans 生成实施计划。
