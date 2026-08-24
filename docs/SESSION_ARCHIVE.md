# MoonTest 会话存档

> 由定时任务（每小时 :07）自动追加。最新快照在最上方，旧的在下。
> 自动过期：recurring 任务 7 天后失效（见 `482991f7`）。

---

## 快照 #2 — 2026-08-24（第 2 次快照）

**当前分支**：master（工作树干净，无未提交改动）

### 未提交改动
无（工作树干净）

### 最近 5 条提交
```
48defb8 feat(ui): CaseGenerate 7-step + SSE, Cases import/export/review cols, CaseDetail version/refine panels, CaseForm/Filter enum align (W5/W6)
93eb7c7 spec(case-to-script): align with requirement verification (14 fixes)
6f6bebe feat(ai_case): GenerationRules + forbidden words + 5 type_labels + token accrual + 4 stages (W6)
b8d4bd2 spec(case-to-script): module #4 design doc
517fb6b feat(review): review/refine fields, CaseRefiner engine, import/export API, refinement API (W4/W5)
```

### 11 模块状态（一句话）
1. **元素库** — 框架完成；P0（batch_import 字段映射）与变更检测/自愈缓存/Redis 键缺口仍未提交修复。
2. **AI智能用例生成** — 持续修：W6 提交 GenerationRules+禁用词+5 type_labels+token 累计+4 stages，W6 前端 7 步+SSE 已提交；前端 SSE/规则开关/禁用词/Token 旧缺口大部分已补。
3. **用例管理** — W1~W4 + W4/W5（review/refine 字段、CaseRefiner 引擎、导入导出 API、版本历史）已提交；新增 `converted` 自动化状态枚举已全栈落地（48defb8）。
4. **用例转自动化脚本** — ⏳ brainstorming 完成 + spec 已对齐需求（93eb7c7，14 项修订）+ `converted` 枚举预备联动；待进入 writing-plans。
5. **UI自动化测试执行** — ⬜ 未开始（#4 运行职责归此）。
6. **执行记录与报告** — ⬜ 未开始。
7. **用例评审与E2E精修** — 部分（CaseRefiner 引擎已随 #3 提交）。
8. **回归测试** — ⬜ 未开始。
9. **白盒代码体检** — ⬜ 未开始。
10. **系统设置** — ⬜ 未开始（token_quota/ai_model_config CRUD 归此，#4 作消费方）。
11. **仪表盘优化** — ⬜ 未开始。

### 本会话进展（自快照 #1）
- **moontest-superpowers 技能更新**：新增 §三「出 spec 前强制需求核对」流程（2 块范围：需求文档页面/字段/规则 + 详细设计架构/流程/机制/异常），禁止项加「未核对就提交 spec」。
- **模块 #4 spec 需求核对**：派 3 并行子代理对照需求文档（页面/字段/规则/API/流程）+ 详细设计（DDL/Redis/SSE/Token/自愈）逐项核对，产出 14 项差异（5 P0 + 5 P1 + 4 P2）。
- **spec 修订并提交**（93eb7c7）：P0 改对齐（ScriptAsset +name/description/project_id+UNIQUE、诊断卡存输入上下文、automation_status 联动、移除运行参数、stage≠scope 术语）；P1 定归属（regression_set/token_quota/diagnostics-apply 等归 #5/#6/#10）；P2 登未决（last_event_id 续传、tokens_estimated_total、<10s/单用例）。
- **`converted` 枚举全栈落地**（48defb8）：schemas+迁移注释+前端下拉/标签+测试断言，65 测试全绿。为 #4 转脚本成功后 TestCase.automation_status='converted' 联动做准备。
- ⚠️ 注意：commit 48defb8 把工作区预先存在的未提交前端改动（ai-case.js/testCase.js/CaseStepEditor/CaseGenerate 的 W5/W6 进度，约 969 行）一并提交了。

### 下一步建议
1. 进入 **writing-plans**：把 #4 spec（5 步流水线 + 数据模型 + API + 调试修复）拆成可执行子任务计划。
2. （可选）若用户希望拆分 48defb8 混合提交，需 reset 后重做（较麻烦）。
3. #1 元素库 P0（batch_import 字段映射）仍未修，迟早要补。

---

---

## 快照 #1 — 2026-08-24（第 1 次快照）

**当前分支**：master

### 未提交改动
- `backend/tests/test_ai_case_rules.py`（未跟踪）
- `backend/tests/test_ai_sse_stages.py`（未跟踪）

### 最近 5 条提交
```
517fb6b feat(review): review/refine fields, CaseRefiner engine, import/export API, refinement API (W4/W5)
2459218 feat(test_case): import/export service xlsx/json/xmind/csv/md (W4)
ac2fe42 feat(test_case): version history API (W3)
788157c feat(test_case): version snapshot on update + rollback (W3)
80e0cc9 feat(test_case): CaseVersion model + migration (W3)
```

### 11 模块状态（一句话）
1. **元素库** — 框架完成；P0（batch_import 字段映射）与变更检测/自愈缓存/Redis 键缺口**未见修复提交**，仍挂着。
2. **AI智能用例生成** — 框架完成；TestPoint.is_deleted bug 已修；前端 SSE/4规则开关/禁用词/Token成本/幻觉比对缺口**未见提交**，仍挂着。
3. **用例管理** — 持续修复中：W1~W4 + 最新 W4/W5（review/refine 字段、CaseRefiner 引擎、评审与导入导出 API）已提交；2 个新增测试文件未提交。
4. **用例转自动化脚本** — ⬜ 进行中（本会话）brainstorming 阶段：范围/定位来源/运行验证/生成架构/入口模式已敲定，待写 spec。
5. **UI自动化测试执行** — ⬜ 未开始（#4 转脚本运行职责归此）。
6. **执行记录与报告** — ⬜ 未开始（AI 诊断页面级分析 + 报告图表归此）。
7. **用例评审与E2E精修** — 部分（CaseRefiner 引擎已随 #3 提交，独立模块未开）。
8. **回归测试** — ⬜ 未开始（复用 #5 自愈引擎）。
9. **白盒代码体检** — ⬜ 未开始（独立模块）。
10. **系统设置** — ⬜ 未开始（独立支撑模块）。
11. **仪表盘优化** — ⬜ 未开始（依赖其他模块数据）。

### 本会话进展（自上次存档/会话起始）
- 确认定时存档机制（持久化 cron `482991f7`，每小时 :07）。
- 启动模块 #4「用例转自动化脚本」Superpowers 流程，进入 brainstorming。
- 敲定 5 个关键设计决策：
  - 范围 = A（仅转脚本流水线，运行/自愈/诊断/报告留下游）。
  - 定位来源 = A（离线查元素库，未命中标草稿，不开浏览器）。
  - 运行验证 = A（纯生成不跑，运行归 #5）。
  - 生成架构 = A（多阶段管线 Step0→4）。
  - 入口模式 = 用例直转 + 调试修复（调试修复调和为"接收失败上下文而非自己运行"）。
- 确认数据模型：ScriptAsset 加 3 列（step_mapping/locator_source/ai_diagnosis），新增 ConvertSession。
- 澄清不做项归属：运行/自愈/AI诊断页面级/报告 → #5/#6；#4 调试修复只做脚本层归因+重生成。
- **待办**：用户确认调试修复调和方式后 → 写 spec → writing-plans → TDD → 编码。

### 下一步建议
1. 等用户确认"调试修复接收失败上下文"的调和方式，即写 spec 到 `docs/superpowers/specs/2026-08-24-case-to-script-design.md`。
2. 提交 spec 后进入 writing-plans，把 5 步流水线拆成可执行子任务。
3. （可选，低优先）核对 #1/#2 挂着的 P0 缺口当前是否已修（memory 3 天前，可能已偏离）。

---
