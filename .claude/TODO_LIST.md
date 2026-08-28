# MoonTest 一期开发待完成项清单

**创建时间**：2026-08-18  
**开发模式**：Superpowers 工程流程  
**状态**：进行中

---

## 📋 开发清单

### ✅ 已完成模块

1. **元素库** (100%) - 2026-08-18
   - Playwright 元素抓取
   - 5种定位策略生成
   - SSE实时推送
   - 批量入库

2. **AI智能用例生成** (P0 完成) - 2026-08-24
   - PRD文档解析（.docx/.pdf/.txt/.md）
   - AI测试点识别（千问/GLM 可插拔）
   - 4规则开关（automation_thinking 强制 + 边界值/场景法/等价类）
   - 禁用词注入（观察/查看/验证/检查/确认）
   - type_label 5枚举（正常流程/异常流程/边界值/等价类/场景法）
   - SSE 4 stage 收敛（parse_doc/identify_point/generate_case/detect_hallucination）
   - Token 累计推送
   - 幻觉检测
   - 7步前端 + 文字直播 SSE 订阅
   - 测试点按 page_name 分组勾选 + 类型筛选

3. **用例管理** (P0 完成) - 2026-08-24
   - 用例CRUD + 列表 + 详情/编辑
   - 枚举/步骤结构全栈统一（JSONB + UNIQUE + 索引）
   - 版本历史（快照/diff/回滚，version 不回退）
   - 导入导出（xlsx/json/xmind 导出 + xlsx/csv/md 导入）
   - 用例评审 5 字段（review_status/comment/feasibility_level/cannot_automate_reason/refinement_report）
   - E2E 精修引擎（规则+LLM 混合，5 维度，同步）
   - 批量操作（delete/finalize/update_review 等）

---

### ✅ P0 缺口补全（W1-W6）- 2026-08-24
依据 `docs/GAP_ANALYSIS_2026-08-20.md`，修复 3 阻断 bug + 补齐缺口：
- W1 is_deleted / 批量定稿 action 修复
- W2 枚举/步骤/JSONB/UNIQUE/索引 + 幂等迁移
- W3 CaseVersion model + 快照/回滚 API + 前端版本历史面板
- W4 ImportExport service + API + 前端导入导出
- W5 评审字段 + CaseRefiner 引擎 + apply-suggestions + 前端评审/精修 UI
- W6 GenerationRules + 禁用词 + 5 type_label + Token 累计 + 4 stage + 前端7步重写
- 迁移脚本：align_test_case_schema / add_case_version_table / add_review_refinement_fields / align_test_point_status

---

### 🔄 待完成模块（下一步）
**状态**：待开始  
**预估时间**：4-5 小时  
**依赖**：用例管理、元素库

**核心功能**：
- [ ] 用例步骤解析
- [ ] 元素库查询和匹配
- [ ] Playwright代码生成
- [ ] 脚本模板引擎
- [ ] 代码预览和编辑
- [ ] 脚本存储和版本管理

---

#### 5. UI自动化测试执行 (0%)
**状态**：待开始  
**预估时间**：5-6 小时  
**依赖**：用例转自动化脚本

**核心功能**：
- [ ] 脚本执行引擎
- [ ] playwright-healer 自愈集成
- [ ] SSE实时执行日志
- [ ] 失败截图保存
- [ ] 执行状态管理
- [ ] 错误重试机制

---

#### 6. 执行记录与报告 (P0 完成) - 2026-08-26
**状态**：✅ 骨架完成（worktree `worktree-module6-execution-reports`，待合回 master）
**预估时间**：3-4 小时  
**依赖**：UI自动化测试执行（#5a execution_record/execution_detail 两表，只读消费）

**核心功能（已落地）**：
- [x] 执行记录列表（项目隔离 + 类型/时间筛选 + 分页，`/reports/records`）
- [x] 执行详情查看（record + 聚合统计 + 失败明细，`/reports/records/{id}`）
- [x] 测试报告生成（Jinja2 HTML + weasyprint PDF + MinIO 上传 + report_url 回写，幂等 + force，`/reports/{id}/generate`）
- [x] 统计图表展示（通过率趋势 ECharts 折线，`/reports/trend`）
- [x] 报告导出（HTML/PDF，`/reports/{id}/export`）
- [x] 失败用例分析（失败步骤明细表 + 截图 + 堆栈，前端 ReportDetail）
- [x] notifier stub（P1 推送预留，钉钉/微信后接）

**诚实边界**：所有测试 mock（无真实 DB/LLM/weasyprint）；weasyprint Windows 未装走 guarded import（PDF 失败非致命）；token_remaining 联调时从 #10 token_service 取。

---

#### 7. 用例评审与E2E精修 (0%)
**状态**：待开始  
**预估时间**：2-3 小时  
**依赖**：用例管理

**核心功能**：
- [ ] 用例评审流程
- [ ] 评审意见记录
- [ ] 用例修改建议
- [ ] AI辅助优化
- [ ] 版本对比

---

#### 8. 回归测试 (0%)
**状态**：待开始  
**预估时间**：2-3 小时  
**依赖**：UI自动化测试执行

**核心功能**：
- [ ] 测试套件管理
- [ ] 批量执行
- [ ] 定时任务（可选）
- [ ] 结果对比

---

#### 9. 白盒代码体检 (P0 完成) - 2026-08-28
**状态**：✅ 骨架完成（worktree `worktree-module9-whitescan`，待合回 master；菜单名已改「白盒测试」）
**预估时间**：4-5 小时  
**依赖**：#2 StepSchema / #3 TestCase / #5a Celery（均已落地，复用不重写）

**核心功能（已落地）**：
- [x] Git集成（repo_url+branch 浅克隆，Celery 异步扫描，broker 不可用 503 降级）
- [x] 静态代码分析（semgrep Docker 方案B，subprocess+@patch 测试；ERROR/WARNING/INFO→high/mid/low）
- [x] 漏洞检测（issue 管理：状态流转 open/fixed/false_positive + WHITE-04 误报指纹忽略）
- [x] AI修复（AIGateway.chat stage=whitescan_ai_fix 埋点 + 坏 JSON 降级；修复建议弹窗含原/修复代码）
- [x] 报告生成（BUG清单 xlsx + Markdown 导出；回归用例一键生成：#2 5 规则+禁用词+强制自动化形式，增量生成查重 source_issue_id）
- [x] 前端 WhiteScan.vue（4 区块：扫描入口/扫描记录+概览/问题列表筛选/产出物下载，轮询 3s + onBeforeUnmount 清理）

**诚实边界**：全 mock（无真实 Docker semgrep/LLM/DB）；semgrep 真实链路+git clone 留联调（需 Docker Desktop 运行）；API 8 端点（spec 9 个中单 issue /generate-case 由批量接口覆盖，计划自身遗漏已记录）；case_outdated 标记字段已建但前端标记展示待联调补。

---

#### 10. 系统设置 (P0 完成) - 2026-08-25
**状态**：✅ 骨架完成（worktree `worktree-module10-system-settings`，待合回 master）
**预估时间**：2-3 小时  
**依赖**：无（支撑性模块）

**核心功能（已落地）**：
- [x] AI模型配置（provider key/URL/默认/fallback 存 DB 可热改 + 测试连接，`/system/settings`）
- [x] Token配额管理（配额/阈值/状态聚合/预警 + `/system/tokens/*`，ai_call_log 埋点）
- [x] 环境变量配置（被测环境 CRUD，`/system/envs`）
- [x] 运行配置（自愈策略/阈值/TTL/超时/重试热改，`/system/runtime-config`）
- [x] 操作日志（`/system/operation-logs`，best-effort helper）
- [ ] ~~用户管理（可选，本期不做）~~

**诚实边界**：所有测试 mock（无真实 DB/LLM），ai_gateway.log_ai_call 的 DB 写路径未覆盖（联调补）；`operator` 参数 dead（接受未用）。

---

#### 11. 仪表盘优化 (P0 完成) - 2026-08-27
**状态**：✅ 骨架完成（worktree `worktree-module11-dashboard`，待合回 master）
**预估时间**：2-3 小时  
**依赖**：其他模块数据（只读 4 表）

**核心功能（已落地）**：
- [x] 数据统计卡片（4 卡：元素/用例/已自动化/测试点，单聚合端点 `/dashboard/overview`）
- [x] ECharts图表集成（元素类型饼 + 用例类型饼 + AI调用趋势折线，真实 API 数据）
- [x] 数据刷新（切换项目/时间/刷新按钮重拉；project_id 可选=全部项目；今日统计 UTC 0 点）
- [x] Token消耗趋势（ai_call_log 按天聚合 count+sum，days 7/30 可选）

**诚实边界**：所有测试 mock（无真实 DB）；「今日」UTC 边界联调时按业务时区调；DashboardService 只读 element_repository/test_case/test_point/ai_call_log 4 表不建表。

---

## 📊 总体进度

- **已完成**：8/11 模块（#1 元素库 / #2 AI生成 / #3 用例管理 / #4 转脚本 / #10 系统设置 / #6 执行记录与报告 / #11 仪表盘 在 master；#9 白盒测试 在 worktree 待合回）
- **待开始**：#5 UI执行 / #7 评审完整页 / #8 回归

---

## 🎯 当前任务

**#6 执行记录与报告**：✅ 已合回 master（2026-08-27）。
**#11 仪表盘优化**：✅ 已合回 master（2026-08-27）。
**#9 白盒测试**：✅ 全部 7 task 完成（T1 models / T2 CodeScanService / T3 AI修复+回归生成器 / T4 编排+Celery+导出 / T5 API 8端点 / T6 前端+菜单改名 / T7 收尾）。worktree `worktree-module9-whitescan` 待合回 master。431 passed，前端 build 通过，8 个 /whitescan/* 路由注册。菜单名已改「白盒测试」。
**集成策略（用户确认 2026-08-24）**：先完成全部模块开发（结构骨架 + 接口契约 + 单测），最后统一接入大模型；数据库迁移在真实联调前一次性执行，再真实测试。AI 模块当前用可插拔占位（ai_gateway 已抽象），不在开发期阻塞。

---

## ⚙️ 开发规则

1. ✅ 每完成一个模块 = brainstorm → plan → TDD → 实现 → 测试
2. ✅ 完成后只提示"已完成测试"，等待用户决定是否继续
3. ❌ 不生成总结报告（除非用户要求）
4. ✅ 严格按照 Superpowers 流程
5. ✅ 保持文档简洁，聚焦开发

---

**最后更新**：2026-08-28
