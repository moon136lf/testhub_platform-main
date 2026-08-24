# 用例转自动化脚本（模块 #4）设计

> 创建：2026-08-24
> 流程：Superpowers brainstorming → spec → writing-plans → TDD → 编码 → 验收
> 依据：需求文档 `docs/requirements_sec_3.5_element_library.md`（页面）、`docs/requirements_extracted.md` §3.3 / §9.2.4 / §9.2.5 / §10.2 / §3.6.3.3 / §3.6.5 / §8.2.6/8.2.8/8.2.9 / §11.4；技能规则 `docs/skills-reference/testcase-to-script-skill.md`
> 需求核对：2026-08-24 派 3 子代理对照需求文档（页面/字段/规则/API/流程）+ 详细设计（DDL/Redis/SSE/Token/自愈）逐项核对，结论已落入本 spec（P0 改对齐、P1 定归属、P2 登未决）。

---

## 1. 目标与边界

### 1.1 本模块做

已定稿用例 → AI 多阶段生成 **Python + Playwright + pytest** 脚本 → 入脚本库 + 文字直播 SSE + 元素库离线定位匹配 + 调试修复（消费失败上下文，不运行脚本）。

支持两种入口模式：
- **用例直转**（主入口，P0）：选已定稿用例 → 批量转脚本。
- **调试修复**：接收失败上下文（来自 #5 执行回传，或用户手动粘贴）→ skill §5.2 四分类归因 → 若可改则重生成失败步骤脚本 → 输出修订版脚本 + 诊断卡。

### 1.2 本模块不做（明确留给下游）

| 不做项 | 归属 | 理由 |
|---|---|---|
| 运行脚本 / 收集通过率 | #5 UI自动化测试执行 | 模块定义即执行引擎 |
| 自愈引擎 Level1-4（§12） | #5 | 定位失败触发自愈发生在运行时 |
| 页面级 AI 诊断 `/diagnostics/analyze`（§9.2.5 TRANS-05，截图+DOM+堆栈打包发 AI，返回 new_locator/confidence/apply_url） | #5 | 需运行产物（截图/DOM），从执行结果页触发 |
| `regression_set` 表（§3.6.5，AI 识别纳入回归集） | #5/#6 | 依赖运行稳定性数据；#4 confirm 时不写 regression_set |
| `token_quota` 表 CRUD + `GET /tokens/status` 预警 UI + `ai_model_config` CRUD | #10 系统设置 | 跨模块基建；#4 仅作消费方（见 §5.1） |
| SSE `last_event_id` 断线续传改造 | 共享基建/#10 | 现有 SSEStream 用 Redis List 下标非稳定 event ID；统一改造避免污染各模块 |
| 执行报告 / 统计图表 | #6 执行记录与报告 | 模块定义即报告 |

### 1.3 #4 与 #5 在"修复"上的分工

```
#5 执行 → 失败 → 截图/DOM/堆栈 (TRANS-04)
                ↓  #5→#4 失败上下文回传契约（字段对齐 §9.2.5 error_data：
                ↓    {step, error_type, error_msg, screenshot_url, dom_snapshot, script_fragment}）
#5 AI诊断 (TRANS-05): 截图+DOM+堆栈+脚本片段 → AI → 修复建议(new_locator, confidence)
                ↓
#4 调试修复 (TRANS-06): 拿建议(或手动粘贴) → 四分类归因 → 重生成失败步骤 → 修订版入库
                ↓
#5 再运行验证
```

- **#5 拥有**：页面级 AI 诊断（`/diagnostics/analyze`，看截图/DOM 给出新 locator 建议，§9.2.5）。
- **#4 拥有**：脚本层归因（skill §5.2 四分类）+ 失败步骤代码重写 + 诊断卡。
- 自愈回写元素库（TRANS-08）归 #5 自愈引擎，#4 不碰。
- #5 建好前 #4 调试修复仍可单跑（手动粘贴模式，跳过页面级诊断）。
- §10.2 时序图把"转脚本"与"自愈执行"画在同一流程，#4 只负责其中"转脚本"段（查询仓库→AI生成→确认入库→脚本生成→文字直播），自愈段属 #5 运行期。

### 1.4 与需求的偏差

| 偏差 | 需求 | 本模块做法 | 理由 |
|---|---|---|---|
| convert+run 拆分 | §9.2.4 `POST /scripts/convert-and-run` 合一 | 拆为 `convert`（#4）+ `run`（#5） | 范围 A 不运行；自愈/诊断/通过率都依赖运行，留 #5 更清晰 |
| 运行参数归属 | §3.3.3 输入字段含运行模式/单测试超时/最大失败数 | 这三项是执行参数，归 #5 的 `run` API；#4 convert 不收不存 | #4 不执行，前端 convert 页移除这三项 |
| 诊断两步流 | §9.2.5 diagnose 返回 `apply_url`，用户点应用才改脚本 | #4 diagnose 直接返回 `revised_script`，一步出结果 | #4 做脚本层重写非页面级 locator 建议；两步流归 #5 `/diagnostics/analyze` |

---

## 2. 数据模型

### 2.1 复用 ScriptAsset（已存在，加列）

`backend/app/models/test_case.py` 的 `ScriptAsset` 表新增（对齐需求 §3.6.3.3 脚本库字段表 + §3.6.5 增强）：

| 列 | 类型 | 说明 | 来源 |
|---|---|---|---|
| `name` | String(100), NOT NULL | 脚本名称（继承用例名），同项目唯一 | §3.6.3.3 P0 |
| `description` | String(500) | 脚本说明 | §3.6.3.3 P1 |
| `step_mapping` | JSONB | skill Step4 步骤对照表 `[{step, case_req, impl, status}]` | skill Step4 |
| `locator_source` | String(20) | `element_library` / `ai_generated` / `mixed` / `none_draft` | 本模块 |
| `ai_diagnosis` | JSONB | 调试修复诊断卡（仅修复版有），结构见 §7.4 | 本模块 |

约束：`UNIQUE(project_id, name)`（脚本名同项目唯一，§3.6.3.3 P0）。`ScriptAsset` 现有 `case_id` 但无 `project_id`——需加 `project_id` 列（FK project）以支撑唯一约束与按项目查询（§3.6.5 列表页按项目过滤）。

`status` 枚举收敛为：
- `draft` — 无定位来源 / 待确认（未命中元素库且未开 AI 生成）
- `generated` — 已生成，待用户确认入库（TRANS-02）
- `confirmed` — 已确认入库（用户点确认后；AI 生成定位器回写元素库）

`category` 入库默认 `uncategorized`（SCRIPT-01，§1463/§1698），复用模型现有默认值。

`last_status`（never_run/passed/failed）仍归 #5 写，#4 只置初值 `never_run`。

### 2.2 新增 ConvertSession（转脚本会话）

类比 `GenerationSession`。一次批量转脚本任务。

```python
class ConvertSession(Base):
    __tablename__ = "convert_session"
    id            = UUID pk
    project_id    = UUID FK project
    case_ids      = JSONB          # 本次转换的用例 ID 列表
    ai_optimize   = Boolean        # 是否对未命中步骤开 AI 生成定位器
    status        = String(20)      # active/done/failed
    progress      = Numeric(5,2)    # 0-1
    tokens_used   = Integer        # 累计 token
    created_at    = DateTime
```

不建 `ConvertStepLog`（YAGNI）：每步日志走 SSE 流 + Redis 临时存，需要持久化审计时再加。

### 2.3 迁移

`backend/migrations/add_convert_script_tables.sql`：
- `script_asset` 加 `project_id`（FK）+ `name` + `description` + `step_mapping` + `locator_source` + `ai_diagnosis`（`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`）。
- 加约束 `UNIQUE(project_id, name)` + 索引 `idx_script_project`。
- 建 `convert_session` 表 + 索引。

---

## 3. 生成流水线（多阶段，skill Step0→4）

每阶段独立可测、有结构化输出。`ai_optimize` 开关控制 Step3 未命中时是否调 AI 生成候选定位器。

| 阶段 | 输入 | 输出 | LLM | 覆盖需求规则 |
|---|---|---|---|---|
| Step0 标准化 | TestCase | 标准化用例（title/steps/expected 缺失则阻塞或生成） | 否（规则） | skill Step0 |
| Step1 步骤→动作意图 | steps | `[{action, target, value}]`，action ∈ navigate/click/fill/select/check/create/edit/delete/workflow_action | 是 | skill Step1 |
| Step2 预期→断言计划 | expected_result + steps[].expected | `[{assertion_type}]`，类型 ∈ toast_message/row_visible/status_changed/field_value/dialog_closed/ambiguous；模糊预期标 `ambiguous` | 是 | skill Step2 |
| Step3 定位匹配 | 动作意图 + ElementRepository | 每动作绑 locator（命中元素库）或标 `待确认`（未命中） | 否（查库）；`ai_optimize=true` 时未命中才调 LLM | TRANS-01/02 |
| Step4 代码生成+对照表 | Step1+2+3 | Playwright+pytest 脚本 + step_mapping 对照表 | 是（拼装） | TRANS-03 |

**TRANS 规则覆盖**（§3.3.4）：TRANS-01 仓库优先→Step3；TRANS-02 确认方入库→§4 confirm；TRANS-03 SSE 文字直播→§4.1；TRANS-04/05/07/08 归 #5（见 §1.2/§1.3）；TRANS-06 应用修复→§7 diagnose。

### 3.1 定位策略（skill §3 硬规则）

- 查 `ElementRepository`：同 project + 页面名/元素名匹配，命中用其 `locator_strategies`。
- 未命中**不开浏览器**：脚本该步用注释占位 `# TODO: 待确认定位器`，不编造 CSS selector。
- `locator_source` 判定：全部命中=`element_library`；全部未命中=`none_draft`；AI 生成=`ai_generated`；混合=`mixed`。
- `ai_optimize=true` 且未命中时：调 LLM 生成候选定位器，标 `ai_generated/pending_confirm`，**TRANS-02 用户确认后方回写元素库**。

### 3.2 断言硬规则（skill §3.3）

- 永真断言黑名单（写进 Step2 prompt + 后置校验）：`expect(button).to_be_visible()` 无业务验证 / `assert len>0` 不筛选 / `assert "字段名" in text` 标签恒在。
- 思想实验自检：注释掉操作后断言还能过 = 无效，必须改。
- 标 `ambiguous` 的断言，注释标"待验证"，待 #5 运行或人工确认后写入知识库。

### 3.3 等待策略（skill §3.4）

生成代码按优先级选等待：expect 自带 > wait_for_response > wait_for(state) > wait_for_load_state(networkidle) > wait_for_timeout(≤500ms 仅动画)。`wait_for_timeout` 仅用于动画，不得作主等待。

---

## 4. API（FastAPI）

路由文件 `backend/app/api/v1/scripts.py`，prefix `/api/v1`。

```
POST /api/v1/scripts/convert
  body: {project_id: uuid, case_ids: [uuid], ai_optimize: bool}
  resp: {session_id} → 前端用 session_id 订阅 SSE

GET  /api/stream/{session_id}                      # SSE 订阅（复用现有 sse.py 路由，prefix /api）

GET  /api/v1/scripts?case_id=&project_id=&page=&page_size=    # 脚本列表

GET  /api/v1/scripts/{script_id}                   # 详情：content + step_mapping + locator_source

PUT  /api/v1/scripts/{script_id}/confirm           # TRANS-02 用户确认入库；AI 定位器回写元素库；
                                                   # ScriptAsset.status→confirmed；
                                                   # TestCase.automation_status→converted（见 §6）
POST /api/v1/scripts/{script_id}/diagnose          # 调试修复（一步出结果，见 §1.4 偏差）
  body: {error_type, error_msg, script_fragment, dom_snapshot?, screenshot_url?, failed_step?}
  resp: {diagnosis_card: {category, can_fix, reason, failed_step, error_type, error_msg,
                          screenshot_url?, revised_step?, suggestion},
         revised_script?, step_mapping?}
```

`error_type` 枚举对齐 skill §5.2 + §3.3.4：`locate_failed` / `timeout` / `assertion_failed` / `script_error`。

`project_id` 进 convert body 便于权限校验与 ConvertSession 关联（§3.3.3 项目选择字段）。

### 4.1 SSE 消息（复用 SSEStream）

`stage="convert_script"`，`type` ∈ system/ai/cost/error。文字直播（skill + §3.3）：
- `开始转换用例 1/N：{name}`
- `匹配全局仓库：{page}.{element} 已找到` / `未找到，AI 生成候选（待确认）`
- `生成步骤 {i}：{action} {target}`
- `转换完成，脚本已生成` + `progress` 递增
- `tokens_used` 真实累计 + `tokens_estimated_total` 线性预估（progress>0 时 `tokens_used/progress`，§6.4；底层 `SSEStream` 已支持该字段）（修 #2 历史问题：Token 实时推送恒 0 → 本模块确保真实值）

---

## 5. 服务层结构

`backend/app/services/` 新增：

```
script_convert_service.py   # 编排：ConvertSession 生命周期 + 5 步调用 + SSE
script_pipeline.py          # 5 阶段纯函数，每阶段独立可测
  ├── step0_normalize(case) -> NormalizedCase
  ├── step1_to_actions(normalized) -> List[ActionIntent]   (LLM)
  ├── step2_to_assertions(normalized) -> List[AssertionPlan] (LLM)
  ├── step3_match_locators(actions, elements) -> List[ActionWithLocator]
  └── step4_generate_code(...) -> (script_str, step_mapping)  (LLM)
script_diagnose_service.py  # 调试修复：四分类 + 重生成失败步骤
script_validator.py         # skill 质量自检 8 项 → validate_script(asset) -> Report
```

边界原则：`script_pipeline` 是纯函数（输入结构 → 输出结构，LLM 通过注入的 gateway 调用，可 mock），`script_convert_service` 拥有 DB + SSE 副作用。两者分离便于单测。

### 5.1 Token 成本与配额

- **调用明细**：复用 `AICallLog`，写 `stage` 列（非 `scope`）= `script_convert` / `ai_fix`（§8.2.9，scope 枚举 §3858 同值但属 `ai_model_config` 列）。每条记录 `tokens_used` + `tokens_cost`（DECIMAL(10,4)），并累加到 `ConvertSession.tokens_used`，SSE 实时推送真实值。
- **按 scope 选模型**：LLM 调用按 `scope=script_convert`（转脚本）/ `scope=ai_fix`（调试修复）从 `ai_model_config` 取模型配置（§3.3"脚本转换模型"下拉，§8.2 ai_model_config.scope）。模型配置 CRUD 归 #10。
- **配额熔断**：每次 LLM 调用前查 `token_quota`（§8.2.8/§11.4）余量，额度耗尽则中止转换 + SSE 推 error（§3.3"Token 额度耗尽暂停所有 AI 调用"）。`token_quota` 表 CRUD + `GET /tokens/status` 预警归 #10。

---

## 6. Celery 任务

`backend/app/tasks/script_tasks.py`：

```python
@celery_app.task(bind=True, name="convert_scripts_task")
def convert_scripts_task(self, session_id, case_ids, ai_optimize):
    sse = SSEStream(session_id)
    # 遍历 case_ids，逐个走 5 步，每步 send_message，写 ScriptAsset
    # 失败的用例记入"不可生成清单"（steps/expected 缺失），不硬凑
```

复用 `ai_case_tasks.py` 的 SSE + Celery 模式。批量转脚本异步执行，前端订阅 SSE 看文字直播。

### 6.1 用例自动化状态联动（CASE-MGMT-04）

转脚本成功写 ScriptAsset（status=generated）后，将对应 `TestCase.automation_status` 流转到「已转脚本」。状态流转链（§1126）：用例定稿 → **已转脚本**（#4 写）→ 脚本运行通过 → 已自动化（后两步归 #5）。

现有枚举 `AUTOMATION_STATUSES = ("pending", "automated", "partial_automated")`（`schemas/test_case.py:10`）缺「已转脚本」值。**需扩枚举**加 `converted`，并在 model/schemas/前端同步。否则 §1126 联动无法落地。

---

## 7. 调试修复（入口模式二）

`script_diagnose_service.py`：

1. 接收失败上下文（`error_type` + `error_msg` + `script_fragment`，可选 `dom_snapshot`/`screenshot_url`/`failed_step`）。
2. 四分类归因（skill §5.2）：
   - `script_problem`（定位器找不到/超时/多用例同函数）→ **可改**，重生成失败步骤。
   - `page_bug`（断言值不符）→ 不可改，标 `xfail`，诊断卡记"页面 Bug"。
   - `data_env`（含"重复/已存在/唯一"或首过二败）→ 不可改，硬停，诊断卡记"数据/环境"。
   - `ambiguous`（信息不足，多为手动粘贴模式）→ 诊断卡标"信息不足，建议补 DOM/截图"。
3. 可改时：调 LLM 重生成 `failed_step` 对应代码段，产出修订版脚本 + 更新 step_mapping，写入 `ScriptAsset` 新版本（version+1）+ `ai_diagnosis` 诊断卡。

### 7.4 诊断卡结构

`ai_diagnosis` JSONB 既存 AI 结论也存输入上下文（便于审计回溯，对齐 §9.2.5 error_data + 失败诊断字段表）：

```json
{
  "category": "script_problem | page_bug | data_env | ambiguous",
  "can_fix": true,
  "reason": "归因理由",
  "failed_step": 3,
  "error_type": "locate_failed",
  "error_msg": "原始错误信息",
  "screenshot_url": "/static/...png",   // 可选，#5 回传时有
  "revised_step": "重生成的代码段",       // 可选，仅 can_fix=true
  "suggestion": "修复建议"
}
```

---

## 8. 前端（Vue3）

新增 `frontend/src/views/ScriptConvert.vue`（§3.3 页面结构，去掉运行/自愈/报告区块，保留转脚本相关）：

- 顶部：项目下拉 + 用例多选 + [批量转脚本] + AI优化开关。（运行模式/单测试超时/最大失败数**移除**——执行参数归 #5，见 §1.4 偏差）
- 文字直播区：SSE 订阅，时间戳逐行显示。
- 脚本预览：代码编辑器（语法高亮）+ [下载脚本]。
- 脚本列表/详情：step_mapping 对照表 + locator_source 标签 + [确认入库]。
- 调试修复入口：脚本详情页 [调试修复] 弹窗，贴 error_msg/script_fragment → 显示诊断卡 + 修订版预览。

路由 `/scripts`。前端 API `frontend/src/api/script.js`。

---

## 9. 测试策略（TDD，核心服务 80%+）

### 9.1 单元测试（mock LLM gateway）

- `script_pipeline` 每阶段：给定输入结构 → 断言输出结构。
  - Step0：缺失 steps/expected → 阻塞列入"不可生成清单"。
  - Step1：navigate/click/fill/select/create/edit/delete 等动作正确映射。
  - Step2：永真断言样本 → 标 invalid；模糊预期 → ambiguous。
  - Step3：元素库命中/未命中/部分命中三分支；locator_source 判定。
  - Step4：生成代码含 step_mapping 对照表，❌ 步骤不得进调试。
- `script_validator.validate_script`：8 项质量自检，喂反例 → 正确标 ❌。
- `script_diagnose_service`：四分类各一个样本 → 正确归类；可改类 → 重生成失败步骤。

### 9.2 集成测试

- API：convert → SSE → GET script → confirm → diagnose 全链路。
- Celery：convert_scripts_task 跑完写 ScriptAsset + 累计 tokens。

### 9.3 skill 硬规则守门测试（防回归）

- 生成代码不得含 `.first`/`.nth`/`.last` 于 click/fill（skill §3.2）。
- 生成代码不得含永真断言（skill §3.3）。
- `wait_for_timeout` 仅动画场景（skill §3.4）。
- 无 DOM 来源时脚本含 `# TODO: 待确认定位器`，不得编造 CSS（skill §3.5）。

---

## 10. 验收标准

1. 选已定稿用例 → 批量转脚本 → SSE 文字直播 → 脚本入 `ScriptAsset`（status=generated，category=uncategorized）。
2. 元素库命中步骤直接引用 locator；未命中标 draft 不编造。
3. AI 生成定位器经用户确认后回写元素库（TRANS-02，转换期回写，#4 负责）。注：TRANS-08 运行期自愈回写归 #5。
4. step_mapping 对照表完整，❌ 步骤阻塞。
5. 调试修复四分类正确，可改类重生成失败步骤；诊断卡含输入上下文。
6. skill 硬规则守门测试全绿。
7. 核心服务测试覆盖 ≥80%。
8. Token 真实累计并经 SSE 推送（非恒 0）+ tokens_estimated_total 线性预估。
9. convert 成功后 TestCase.automation_status 流转到 `converted`（CASE-MGMT-04）。
10. LLM 调用前查 token_quota，额度耗尽中止 + SSE error。
11. 单用例转脚本 <10s（§10.2 性能目标，P1）。

---

## 11. 未决 / 待 writing-plans 细化

- LLM prompt 模板的精确内容（writing-plans 阶段细化，TDD 时用 mock 验证结构而非具体文案）。
- 元素库匹配的相似度算法（精确匹配元素名 vs 模糊匹配，先精确，模糊留 P1）。
- 批量转脚本的并发度（串行先实现，性能问题再优化）。
- **SSE `last_event_id` 断线续传**：现有 SSEStream 用 Redis List 下标去重，非稳定 event ID，重连/TTL 过期后续传失效。归共享基建/#10 统一改造（Redis List→Stream + 端点加 `last_event_id` 查询参数），#4 不单独改 sse.py 避免污染其他模块流。本模块先用现有 SSEStream。
- `token_quota` / `ai_model_config` 表本模块假设 #10 已建或与 #4 同期建最小消费接口；若 #10 未就绪，#4 需先建只读查询部分。
