# MoonTest 测试平台 需求文档（V1.1 整合版）

**文档版本**：V1.1（以代码实现现状为准修订 V1.0）
**编制日期**：2026-09-02
**阅读对象**：前端开发、后端开发、测试开发、DBA
**修订基准**：V1.0（2026-08-17，`docs/design-doc-raw.xml`）→ 按当前代码实现现状全面修订。字段、枚举、接口以 `backend/app` 实际代码为准；与 V1.0 的差异在文中以【V1.1变更】标注。

---

## 第0章 V1.1 变更总览

| 类别 | 变更 |
|---|---|
| 架构 | 移除 LangChain（直接调大模型网关）；AI 网关五 provider（glm-4/qwen/deepseek/claude/moonshot）+ `AI_FALLBACK_PROVIDERS` 兜底链；Embedding 走 Qwen `text-embedding-v3` |
| 自愈 | Level4 视觉模型确定接入 kimi-2.6（moonshot provider，多模态） |
| 白盒 | 新增 CodeStructureAnalyzer（静态解析前端路由+后端端点）、功能用例生成端点 `POST /whitescan/scans/{scan_id}/generate-cases`、扫描产出物导出 |
| 规则 | 新增测试规则管理（`test_rule` 表 + `/rules` GET/POST/PUT/DELETE 全 CRUD，内置规则+自定义规则） |
| 菜单 | "UI自动化测试"页面合并进脚本库（redirect→/scripts）；无登录页 |
| 本期不做 | 登录/认证模块（用户明确不做）、协议模拟（代码未实现，见 §5.5）、报告推送 webhook（仅日志桩）、定时调度深度开发 |
| 数据模型 | 22+ 张表以 SQLAlchemy models + `backend/migrations/` 为准；知识库 pgvector `vector(1536)` |

**实现状态标注约定**：每个模块尾部标注 ✅已实现 / 🟡骨架或部分桩 / ❌未实现。

---

## 第1章 文档概述

### 1.1 编写目的
本文档为 MoonTest 测试平台 V1.1 的需求与详细设计文档，覆盖：完整的页面级功能规格、每个字段的类型/长度/校验规则/默认值、核心业务逻辑、数据库设计、接口定义与异常处理方案。

### 1.2 优先级定义
- **P0**：MVP 必须交付，阻塞核心闭环
- **P1**：MVP 应交付，影响完整度但不阻塞闭环
- **P2**：后续迭代，本期预留骨架/接口

### 1.3 项目范围
元素库管理、AI 测试用例生成与管理、用例转 Playwright 自动化脚本、UI 自动化执行与自愈、接口测试（文档解析、加密登录、单接口调试、一键测试）、回归测试、白盒代码体检、知识库（RAG）、执行记录与报告、Token 成本管理、系统设置。

### 1.4 菜单架构全景（以前端 router 实际实现为准）

```
MoonTest 平台
├── 📊 仪表盘（Dashboard）
├── 📁 项目管理（ProjectManagement）
├── 🤖 AI智能
│   ├── 用例生成（ai/CaseGenerate）
│   ├── 知识库管理（ai/KnowledgeManagement）🟡前端 mock
│   ├── 测试规则管理（ai/RuleManagement）
│   └── 生成历史（ai/GenerationHistory）🟡前端 mock
├── 🗂️ 元素库（ElementLibrary）
├── 📋 用例管理（Cases / CaseDetail）
├── ⚙️ 用例转脚本（ScriptConvert）
├── 🧪 回归测试（Regression）
├── 📈 执行记录与报告（reports/ExecutionList + ReportDetail）
├── ✍️ 用例评审与E2E精修（reviews/ReviewCenter）
├── 🩺 白盒测试（whitescan/WhiteScan）
└── ⚙️ 系统设置
    ├── AI设置（system/AISettings）
    ├── 运行配置（system/RuntimeConfig）
    ├── 环境管理（system/EnvManagement）
    └── Token成本管理（system/TokenDashboard）

【V1.1变更】"UI自动化测试"一级菜单取消，功能并入脚本库页（redirect→/scripts）；
无协议模拟页面（本期未实现）；无登录页（认证本期不做）。
```

---

## 第2章 概览模块

### 2.1 仪表盘 ✅
**字段定义**：

| 字段 | 类型 | 逻辑/说明 | 优先级 |
|---|---|---|---|
| 入库元素数 | 整数 | 当前项目元素库总数（element_repository COUNT）| P1 |
| 测试用例数 | 整数 | 当前项目用例总数 | P1 |
| 已自动化数 | 整数 | automation_status='automated' 的用例数 | P1 |
| 测试点数 | 整数 | 当前项目测试点总数 | P1 |
| 今日AI调用次数 | 整数 | 当日 AI API 调用总数 | P1 |
| 今日Token消耗 | 整数 | 当日 Token 消耗总量 | P1 |
| 元素类型分布 | 饼图 | button/input/select/other 维度 | P1 |
| 用例类型分布 | 饼图 | 功能/接口 维度 | P1 |
| AI调用趋势 | 折线图 | 近7天/近30天，调用量+Token | P1 |

**交互规则**：项目切换→所有统计切换项目范围；时间筛选→趋势图刷新；刷新→重载全部数据。

**API**：`GET /api/v1/dashboard/overview`

### 2.2 项目管理 ✅
**字段定义**：

| 字段 | 必填 | 类型 | 限制 | 校验 | 默认值 | 优先级 |
|---|---|---|---|---|---|---|
| 项目名称 | 是 | 文本 | 1-50字符 | 唯一 | 无 | P0 |
| 项目编码 | 是 | 文本 | 1-20字符 | 唯一，大写字母/数字/下划线 | 无 | P0 |
| 项目描述 | 否 | 长文本 | 0-500字符 | — | 空字符串 | P1 |
| 被测应用URL | 是 | URL | ≤500字符 | 合法URL | http://localhost:81 | P0 |
| 状态 | 是 | 枚举 | active/archived | — | active | P0 |
| 创建人 | 自动 | 文本 | — | DEFAULT_USER（认证未做）| — | P0 |
| 创建/更新时间 | 自动 | 时间戳 | — | — | 系统时间 | P0 |
| 软删除 | 自动 | 布尔 | — | — | false | P0 |

**业务规则**：
- PM-01 所有测试资产（元素、用例、脚本、执行记录）必须归属某项目
- PM-02 删除项目前确认：无资产可删；有资产提示"存在X个元素、Y个用例，请先迁移"
- PM-03 软删除（is_deleted=true）

**API**：`GET/POST /api/v1/projects`、`GET/PUT/DELETE /api/v1/projects/{id}`

---

## 第3章 AI与用例模块

### 3.1 AI智能用例生成 ✅
**页面概述**：输入 PRD/设计文档/原型，AI 识别测试点，用户勾选后批量生成测试用例，附幻觉检测。

**输入材料区字段**：

| 字段 | 必填 | 类型 | 限制 | 校验 | 默认值 | 优先级 |
|---|---|---|---|---|---|---|
| 项目选择 | 是 | 下拉 | — | 必须选已有项目 | 当前项目 | P0 |
| PRD文档 | 否 | 文件 | ≤10MB | .docx/.pdf/.txt/.md | 无 | P0 |
| 设计方案 | 否 | 文件 | ≤10MB | .docx/.pdf/.txt/.md | 无 | P0 |
| UI原型 | 否 | 文件 | ≤10MB | .png/.jpg/.pdf | 无 | P0 |
| 需求文本 | 否 | 长文本 | ≤50000字符 | — | 空 | P0 |

校验：至少提供一种材料。

**规则配置区**（四开关，注入生成 prompt）：

| 规则 | 默认 | 说明 | 优先级 |
|---|---|---|---|
| 自动化思维规则 | 开启（强制）| 禁用"观察/验证/查看"，强制"点击/填充/断言" | P0 |
| 边界值分析 | 开启 | 生成边界值测试点 | P1 |
| 场景法覆盖 | 开启 | 生成正常/异常场景 | P1 |
| 等价类划分 | 开启 | 生成等价类测试点 | P1 |

**测试点字段**：名称（1-100）、所属页面（1-50）、类型标签（正常流程/异常流程/边界值/等价类/场景法）、描述（0-500）、来源片段（≤500，材料原文出处便于追溯）、状态（pending/approved/rejected）。

**SSE 文字直播消息**：7 字段 —— timestamp(ISO8601)、type(system/ai/user/error/cost)、stage、content(≤200)、progress(0-1)、tokens_used、tokens_estimated_total。stage 枚举（V1.1 以实现为准）：parse_doc / identify_point / generate_case / detect_hallucination / rag_retrieval / convert_script / execute / self_heal。

**业务逻辑**：
- CASE-01 材料打包发送 AI，返回按页面分组的测试点清单
- CASE-02 全程 SSE 文字直播：解析文档→提取功能点→按页面分组→生成测试点
- CASE-03 勾选测试点后逐条生成用例
- CASE-04 生成时强制注入自动化思维规则（禁用词列表进 prompt）
- CASE-05 幻觉检测：①禁用词检测；②与 PRD 语义比对标记矛盾项
- CASE-06 疑似幻觉用例标记（⚠️+橙色），人工复核后定稿
- CASE-07 生成进度 SSE 实时推送（第X/Y条）
- CASE-08 Token 消耗实时推送（已消耗+预估总消耗）
- RAG-01 编排器阶段1：需求文本向量化 → pgvector 检索知识库（按来源范围过滤）→ 相似度≥阈值取 TopK → 按注入策略注入 prompt；检索失败自动降级"仅PRD"模式（stage 标 degraded）

**实现状态**：✅后端主干（解析/识别/生成/幻觉检测/SSE）；🟡材料解析前端有拼字符串占位；🟡知识上下文注入为硬编码字符串（RAG 真实注入待真实化阶段）。

**API**：`POST /upload-document`、`POST /search-knowledge`、`GET /knowledge-results/{session_id}`、`POST /identify-points`、`GET/POST /test-points`、`PUT /test-points/{id}`、`POST /generate-cases`

### 3.2 用例评审与E2E精修 ✅
**字段定义**：

| 字段 | 类型 | 限制 | 说明 | 优先级 |
|---|---|---|---|---|
| 评审状态 | 枚举 | 待评审/已通过/需修改 | PATCH /review 更新 | P0 |
| 评审意见 | 长文本 | 0-500字符 | 评审人填写 | P1 |
| 可行性等级 | 枚举 | 完全自动化/部分自动化/需手工执行 | AI 判断 | P1 |
| 不可自动化原因 | 文本 | 0-200字符 | 如"涉及验证码识别" | P1 |
| 精修报告 | JSON | — | 结构化精修建议列表 | P0 |
| 精修评分 | 整数 | 0-100 | 用例质量评分 | P1 |

**业务逻辑**：
- REVIEW-01 评审状态流转：待评审→已通过/需修改→修改后重新评审
- REVIEW-02 可行性分析 AI 判断：全部步骤可定位→完全自动化；部分需人工→部分；涉及验证码/视觉→手工
- REVIEW-03 精修器扫描用例质量，输出精修报告（缺失断言/前置不完整/步骤模糊）
- REVIEW-04 建议逐条确认或一键应用全部
- REVIEW-05 精修通过后可进入脚本转换工序

**实现状态**：✅核心在；🟡评审状态筛选为前端过滤（后端无参数）；🟡case_refiner 异常路径建议部分硬编码（LLM 未全接）。

**API**：`GET /reviews/stats`、`POST /reviews/batch-refine`、`GET /reviews/refinement-report`、`POST /reviews/batch-review`、`PATCH /test-cases/{id}/review`、`POST /test-cases/{id}/refine`、`GET /test-cases/{id}/refinement-report`、`POST /test-cases/{id}/apply-suggestions`

### 3.3 用例转自动化脚本 ✅
**输入字段**：

| 字段 | 必填 | 类型 | 默认值 | 说明 | 优先级 |
|---|---|---|---|---|---|
| 项目选择 | 是 | 下拉 | 当前项目 | — | P0 |
| 用例选择 | 是 | 多选 | 无 | 已定稿用例 | P0 |
| AI优化脚本 | 否 | 开关 | 开启 | 是否用AI优化 | P0 |
| 运行模式 | 否 | 枚举 | 无头 | 有头/无头 | P0 |
| 单测试超时 | 否 | 整数 | 60（秒，5-600）| — | P0 |
| 最大失败数 | 否 | 整数 | 8（1-100）| — | P0 |

**脚本/执行/诊断字段**：同 V1.0 §3.3.3（脚本ID、关联用例、脚本内容、版本、执行状态五态、通过率、失败步骤、错误类型四分类【定位失败/超时/断言失败/脚本错误】、截图URL、DOM快照、AI诊断结果、自愈状态）。

**业务逻辑**：
- TRANS-01 转换时第一优先级查询全局页面仓库，命中直接引用定位器，未命中 AI 生成
- TRANS-02 AI 生成定位器需人工确认入库（`PUT /scripts/{id}/confirm`）
- TRANS-03 转换过程 SSE 文字直播
- TRANS-04 运行失败自动截屏+DOM+错误堆栈（落 MinIO）
- TRANS-05/06 AI 诊断→修复建议→应用修复
- TRANS-07 定位失败触发自愈引擎（§9.1）
- TRANS-08 自愈成功且置信度≥3 回写全局仓库
- TRANS-09（V1.1新增）转换成功后用例 automation_status 联动为 converted；5 阶段纯函数 pipeline + 8 项守门 validator

**实现状态**：✅（convert/run/batch-run/quick-run/diagnose/confirm 端点 + Celery 任务）；🟡快速运行粘贴脚本同页支持；🟡断言校验 `_check_assertion` 对 field_value/status_changed 等类型占位假通过（P2 假成功点）。

**API**：`POST /scripts/convert`、`GET /scripts`、`GET /scripts/stats`、`POST /scripts/run`、`POST /scripts/batch-run`、`POST /scripts/quick-run`、`GET /scripts/{id}`、`PUT /scripts/{id}/confirm`、`POST /scripts/{id}/diagnose`

### 3.4 用例管理 ✅
**字段定义**：

| 字段 | 必填 | 类型 | 限制 | 校验 | 默认值 | 优先级 |
|---|---|---|---|---|---|---|
| 用例名称 | 是 | 文本 | 1-100字符 | 同项目唯一 | 无 | P0 |
| 关联测试点ID | 否 | UUID | — | 弱关联（V1.1：可空）| 无 | P0 |
| 优先级 | 是 | 枚举 | P0/P1/P2/P3 | — | P1 | P0 |
| 用例类型 | 是 | 枚举 | functional/api | 【V1.1】收敛为功能/接口 | functional | P0 |
| 自动化状态 | 自动 | 枚举 | 未转化/已转化/已自动化 | 【V1.1】pending/converted/automated | pending | P0 |
| 前置条件 | 否 | 长文本 | 0-500字符 | — | 空 | P0 |
| 测试步骤 | 是 | JSON | 每步≤200字符 | {seq,action,target,data,expected} | 无 | P0 |
| 预期结果 | 是 | 长文本 | 0-200字符 | — | 无 | P0 |
| 是否定稿 | 是 | 布尔 | — | — | false | P0 |
| 幻觉标记 | 枚举 | normal/suspected/confirmed | — | normal | P0 |
| 版本号 | 自动 | 整数 | 递增 | — | 1 | P1 |
| 创建人/时间/更新时间 | 自动 | — | — | — | — | P0 |

**业务规则**：
- CASE-MGMT-01 软删除，保留30天
- CASE-MGMT-02 每次修改记录版本历史（case_version 表），支持 diff 与回滚（`GET /{id}/versions`、`POST /{id}/rollback`）
- CASE-MGMT-03 导入 .xlsx/.csv/.md；导出 .xlsx/.json/.xmind（`POST /import`、`GET /export`）
- CASE-MGMT-04 自动化状态自动流转：定稿→已转脚本(converted)→运行通过→已自动化(automated)

**实现状态**：✅（含版本历史/回滚/导入导出/批量操作）。

**API**：`GET/POST /test-cases`、`PUT/DELETE /test-cases/{id}`、`GET /test-cases/export`、`POST /test-cases/import`、`GET /test-cases/stats`、`POST /test-cases/batch`、`GET /test-cases/{id}/versions[/{version}]`、`POST /test-cases/{id}/rollback`

### 3.5 元素库 ✅
**元素表字段**（V1.1 以 models 实现为准）：

| 字段 | 必填 | 类型 | 说明 | 优先级 |
|---|---|---|---|---|
| 元素ID | 自动 | UUID | — | P0 |
| 页面ID | 是 | UUID | 必须存在 | P0 |
| 元素别名 | 是 | 文本 | 1-50字符 | P0 |
| 元素类型 | 是 | 枚举 | button/input/link/select/other | P0 |
| 显示文本 | 否 | 文本 | 0-100字符 | P1 |
| 坐标X/Y、宽高 | 是 | 整数 | ≥0 | P0 |
| 定位策略链 | 是 | JSON | `locator_strategies: {strategies:[{type,value,priority}]}`，id/css/xpath/text/role 五种 | P0 |
| 置信度 | 自动 | 整数 | 0-100 | P0 |

**页面表**：页面名称（同项目唯一）、页面URL路径（同项目唯一【V1.1变更：字段名 page_url】）、页面截图、元素数量。

**抓取历史**：抓取ID、URL、元素数量、状态（成功/失败/部分成功）、抓取时间、操作人。

**变更检测**：对比基准/本次抓取ID、新增/删除/变更元素JSON、影响脚本数、检测时间【V1.1实现：逐条 change_type 记录 + change_detection_service 对比】。

**业务逻辑**：
- ELEM-01 抓取时识别页面唯一标识（URL path+页面标题）
- ELEM-02 入库强制确认页面归属（已有页面归类/新建页面）
- ELEM-03 自动提取5种定位策略
- ELEM-04 点击截图反查最近 DOM 节点
- ELEM-05 变更检测对比历史抓取
- ELEM-06 变更影响脚本标记"受影响"
- ELEM-07 一键更新引用脚本定位器（`POST /change-detection/{id}/fix`）

**实现状态**：✅后端（fetch/import/pages/history/change-detection/fix）；🟡前端截图红框高亮叠加、抓取历史区块部分缺失；🟡Redis 键（page_repo/element/heal_cache）未接。

**API**：`POST /elements/fetch`、`POST /elements/import`、`GET /elements/pages`、`GET /elements/pages/{id}/elements`、`GET /elements/pages/{id}/history`、`DELETE /elements/{id}`、`POST /elements/change-detection`、`POST /elements/change-detection/{id}/fix`

### 3.6 测试规则管理（V1.1新增）✅
**页面概述**：AI 生成/转换所用的提示词规则模板管理，内置规则+自定义规则。

**字段定义**（test_rule 表）：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| 名称 | 是 | 文本 | 规则标识 |
| 描述 | 否 | 文本 | 用途说明 |
| prompt_template | 否 | 长文本 | 提示词模板 |
| is_builtin | 自动 | 布尔 | 内置规则不可删除 |
| status | 是 | 枚举 | 启用/停用 |

**API**：`GET/POST /rules`、`PUT/DELETE /rules/{rule_id}`（内置规则禁止删除）

---

## 第4章 自动化模块

### 4.1 脚本库与 UI 自动化 ✅
**页面概述**：脚本资产统一管理、单脚本/批量/快速运行、统计卡片。【V1.1变更】原"UI自动化测试"独立页面并入本页（redirect→/scripts）。

**脚本库字段**：

| 字段 | 类型 | 说明 | 优先级 |
|---|---|---|---|
| 脚本ID/关联用例ID | UUID | — | P0 |
| 脚本内容 | 长文本 | Playwright Python 代码 | P0 |
| 脚本版本 | 整数 | 从1递增 | P1 |
| 状态 | 枚举 | 通过/失败/从未运行/受影响 | P0 |
| 分类 | 枚举 | 未分类/UI冒烟/全量回归/核心流程/接口自动化 | P0 |
| 所属模块 | 文本 | 如"登录鉴权" | P0 |
| 是否纳入回归集/AI建议纳入/AI建议原因 | 布尔/文本 | AI识别+人工调整 | P0 |
| 运行次数/最后运行时间 | 整数/时间戳 | 自动累计 | P1 |

**业务逻辑**：
- SCRIPT-01 转换成功脚本自动入脚本库，默认"未分类"
- SCRIPT-02 按分类筛选、按名称搜索
- SCRIPT-03 单脚本运行更新状态/次数/最后运行时间
- SCRIPT-04 批量运行生成汇总报告（`POST /batch-run`，失败策略继续/停止）
- SCRIPT-05 快速运行粘贴脚本临时执行不入库（`POST /quick-run`）
- SCRIPT-06 运行失败可查看截图报告并触发 AI 诊断/自愈
- SCRIPT-07 元素变更命中时受影响脚本标记"受影响"高亮

**统计卡片**：总脚本数/通过/失败/从未运行/通过率（`GET /scripts/stats`）。

### 4.2 回归测试 ✅
**字段定义**（regression_set 表）：

| 字段 | 类型 | 说明 | 优先级 |
|---|---|---|---|
| 项目ID/脚本ID | UUID | UNIQUE(project_id, script_id) | P0 |
| ai_suggested | 布尔 | AI 判定结果 | P0 |
| ai_reason | 文本≤200 | 如"P0核心用例，历史通过率稳定" | P1 |
| actual_included | 布尔 | 实际纳入（AI建议+人工调整）| P0 |
| include_source | 枚举 | ai/manual | P1 |
| included_at | 时间戳 | 纳入时间 | P1 |

**AI识别回归规则**（regression_rules 六规则纯函数 score_script，总分≥3 纳入）：用例优先级（高权重）、历史通过率≥80%（高）、核心流程覆盖（中）、模块代表性（中）、运行稳定性（中）、依赖复杂度（低）。

**业务逻辑**：
- REG-01 回归集 = actual_included=true 的脚本集合
- REG-02 AI 识别写入 ai_suggested/ai_reason
- REG-03 人工可调整（confirm hook，begin_nested savepoint 隔离）
- REG-04 批量执行（exec_type=ui_regression，fail_fast 参数）
- REG-05 回归报告含通过率、失败详情、截图；导出✅、推送🟡（桩）
- REG-06 回归执行同步更新脚本库状态/次数/最后运行时间

**实现状态**：✅（8 端点）；🟡报告推送为日志桩（`notifier.py` 仅返回 pushed:true）。

**API**：`GET /regression/list`、`POST /regression/members`、`POST /regression/identify`、`GET /regression/stats`、`POST /regression/run`、`GET /regression/latest-execution`、`POST /regression/{exec_id}/push`（桩）、`GET /regression/report-summary`

---

## 第5章 接口与执行模块

### 5.1 接口文档解析 🟡
同 V1.0 §4.1：导入 .json/.yaml/.yml（Swagger 2.0/OpenAPI），解析提取路径/方法/参数/响应；相同路径+方法视为同一接口，新导入覆盖旧版；每接口保留最近10个版本变更历史；触发策略（代码提交 Webhook/定时/手动）。

**实现状态**：🟡本期按需求保留设计，接口管理链路骨架级。

### 5.2 接口管理 🟡
同 V1.0 §4.2：接口资产维护、加密登录配置（RSA/AES/MD5/自定义 + 公钥 + 算法 SHA256/SHA1/MD5 + 编码 Base64/Hex）、前置脚本（Python，请求前/响应后执行，可访问请求参数和全局变量）、AI 生成边界用例（等价类/边界值/必填校验/类型错误/特殊字符）。

### 5.3 单接口调试 🟡
同 V1.0 §4.3：环境切换、`{{variable}}` 变量替换、前置/后置脚本自动执行、响应 JSON 格式化、一键提取字段存环境变量、调试通过一键保存为接口用例。

### 5.4 一键测试 🟡
同 V1.0 §4.4：五步流水线（导入接口→AI生成用例→审核调整→执行测试→生成报告），AI 生成用例同时生成 Mock 数据，报告含通过率/失败项/Mock校验/Token消耗。

### 5.5 协议模拟 ❌ 本期未实现
**【V1.1变更】** V1.0 标 P0，当前代码无任何 MQTT/HTTP 模拟实现（后端无 mqtt/simulator 模块，前端无页面）。设计保留 V1.0 §4.5（MQTT/HTTP 设备上下行模拟、变量语法 `{{device_id}}/{{random.int(min,max)}}/{{timestamp}}/{{uuid}}`、QoS 0-2、批量模拟、数据仅本地存储），排期至后续迭代。

---

## 第6章 知识库（RAG）✅
**技术选型**：PostgreSQL + pgvector（不引新组件），Embedding 走 AI 网关 Qwen `text-embedding-v3`，向量维度 1536，分块 500 字符 + 重叠。

**三张表**（替代 V1.0 knowledge_base 单表）：
- `knowledge_document`：文档来源类型（需求文档/历史Bug/历史用例）、标题、MinIO 文件路径、格式（docx/pdf/md/xlsx/csv/xmind，≤20MB）、标签、上传人/时间、向量化状态（pending/processing/done/failed）、chunk总数、失败原因
- `knowledge_chunk`：document_id、chunk_no、chunk_content、`embedding vector(1536)`、source_type，IVFFlat 余弦索引 lists=100
- `knowledge_record`：自动采集（执行失败/自愈成功）与人工录入（业务规则/避坑指南/测试经验）、标题、正文、标签、向量化状态、embedding

**检索配置**：检索开关（默认开）、TopK（默认5，1-20）、相似度阈值（默认0.7）、注入策略（仅PRD/PRD+检索/仅检索）、检索来源范围（多选）。

**检索测试**：输入 query → 向量化 → pgvector 余弦检索 → 返回 TopK + 相似度评分 + 来源文档。

**业务逻辑**：上传→MinIO→解析→分块→逐块 Embedding→写 chunk；失败可重试；文档删除级联删 chunk；脚本运行失败/自愈成功自动采集入 knowledge_record。

**实现状态**：✅后端（knowledge_service + document_parser + pgvector 检索）；🟡前端 KnowledgeManagement.vue 文档列表/删除/重试为 mock（P1 假成功点，待真实化销号）；🟡生成流程知识上下文注入硬编码（ai_case_tasks.py）。

**API**：`POST /search-knowledge`、`GET /knowledge-results/{session_id}`（其余文档 CRUD 端点待补）。

---

## 第7章 质量与报告模块

### 7.1 白盒代码体检 ✅
**页面概述**：代码质量扫描、AI 修复建议、静态结构分析、产出物导出、从仓库结构生成功能回归用例。

**字段定义**（code_scan / code_issue 表）：

| 字段 | 类型 | 说明 | 优先级 |
|---|---|---|---|
| 扫描ID/项目ID/仓库路径/分支 | — | 一次扫描会话 | P0 |
| 问题ID | UUID | code_issue | P0 |
| 严重等级 | 枚举 | 高危/中危/低危 | P0 |
| 文件路径/行号 | 文本/整数 | 定位 | P0 |
| 问题描述/详情 | 文本/长文本 | — | P0 |
| AI修复建议/示例代码 | 长文本 | LLM 生成 | P1 |
| 状态 | 枚举 | 待处理/已修复/误报忽略 | P0 |
| 处理人/处理时间 | — | 状态变更记录 | P1 |

**业务逻辑**：
- WHITE-01 扫描规则库：SQL注入、XSS、空指针、硬编码密钥、日志脱敏、未处理异常等
- WHITE-02 AI 修复建议含解释+示例代码（`POST /issues/{id}/ai-fix`）
- WHITE-03 标记"误报忽略"后同一场景不再告警
- WHITE-04 产出物：BUG清单.xlsx、API契约矩阵.md、功能点清单.md 等（`GET /scans/{id}/export`）
- WHITE-05（V1.1新增）CodeStructureAnalyzer：静态解析前端路由块+后端端点块（`analyze_frontend`/`analyze_backend`）
- WHITE-06（V1.1新增）功能用例生成：按扫描所得仓库结构（菜单/API 分批）→ LLM 生成功能回归用例 → JSON 解析 → 去重 → 保存 test_case（`POST /scans/{id}/generate-cases`，含 token 追踪与非 dict 守门）

**API**：`POST /whitescan/scan`、`GET /whitescan/scans[/{id}][/issues]`、`PATCH /whitescan/issues/{id}`、`POST /whitescan/issues/{id}/ai-fix`、`POST /whitescan/scans/{id}/generate-cases`、`GET /whitescan/scans/{id}/export`

### 7.2 执行记录与报告 ✅
**字段定义**（execution_record / execution_detail）：

| 字段 | 类型 | 说明 | 优先级 |
|---|---|---|---|
| 执行ID | 文本 | exec_id，唯一 | P0 |
| 执行类型 | 枚举 | ui_regression/接口/白盒/组合 | P0 |
| 执行状态 | 枚举 | 待执行/执行中/成功/失败/超时 | P0 |
| 总用例/通过/失败数、通过率 | 整数/小数 | — | P0 |
| 总耗时/Token消耗 | 整数 | — | P1 |
| 报告URL/环境信息JSON | — | MinIO 路径 | P0 |

**业务规则**：记录自动归档按项目隔离；报告导出 HTML/PDF；趋势图近7/30/90天通过率变化（`GET /reports/trend`）；报告推送钉钉/飞书/邮件🟡桩；记录保留180天。

**API**：`GET /reports/records[/{exec_id}][/details]`、`GET /reports/trend`、`POST /reports/{exec_id}/generate`、`GET /reports/{exec_id}/export`

### 7.3 任务调度 🟡（骨架）
同 V1.0 §5.3：本期仅手动触发立即执行+执行历史复用；定时执行（Cron）与策略编排暂缓，P2。

---

## 第8章 系统设置 ✅

### 8.1 AI设置
**模型配置**：AI 网关支持五 provider —— glm-4（模型 glm-5.2）、qwen、deepseek、claude、moonshot（kimi-2.6，多模态，Level4 视觉自愈专用显式 provider）。`AI_FALLBACK_PROVIDERS` 兜底链，某 provider 失败自动降级下一个。API Key 加密存储（AES-256-GCM），前端掩码显示。"测试连接"发测试请求返回状态。模型配置保存即时生效，无需重启。

**【V1.1待办】** 按 scope 配模型（ai_model_config 按场景：case_generate/script_convert/ai_fix/self_heal/debug 各自独立指定模型）为已知待办，当前模型选择按 provider 默认+配置，非 per-scope 路由。

**Token管理**（token_quota 表 + token_service）：总额度（默认100000）、已消耗、剩余、预警阈值（默认10%）、`GET /system/tokens/status`（percentage/is_warning/预估剩余天数）、`GET/PUT /system/tokens/quota`、`GET /system/tokens/usage`。额度耗尽暂停 AI 调用弹窗预警。每次 AI 调用落 `ai_call_log`（model/tokens_used/stage/status）。

### 8.2 运行配置（RuntimeConfig）
| 字段 | 默认值 | 范围 |
|---|---|---|
| 默认运行模式 | 无头 | 有头/无头 |
| 单测试超时 | 60s | 5-600 |
| 最大失败数 | 8 | 1-100 |
| 执行超时 | 600s | 60-3600 |
| AI调用最大重试 | 3 | 0-10（指数退避1s/2s/4s）|
| 自愈成功TTL | 30天 | 1-365 |
| 自愈失败TTL | 1小时 | 1-720 |
| 自愈置信度回写阈值 | 3 | 1-10 |

**API**：`GET /system/runtime-config`、`GET/PUT /system/settings[/{key}]`、`POST /system/settings/test-connection`

### 8.3 环境管理（test_env 表）
环境名称（开发/测试/预发布/生产）、Base URL、全局变量 JSONB、当前激活环境。`GET/POST /system/envs`、`PUT/DELETE /system/envs/{id}`。

### 8.4 操作日志（operation_log 表）
操作人、操作类型（新增/修改/删除/执行/导出/配置变更）、操作对象、详情 JSONB、IP、时间。关键操作自动记录；按项目隔离；保留180天。`GET /system/operation-logs`。

### 8.5 用户管理 ❌ 本期不做
用户明确不做登录/认证模块。当前无 JWT 签发、无用户表、无登录页；所有端点未认证；`created_by` 使用 DEFAULT_USER 常量（代码 TODO 标注待接认证）。`core/security.py` 仅保留 AES-256-GCM 密钥加密（种子取自 JWT_SECRET_KEY）。

---

## 第9章 核心机制

### 9.1 自愈引擎（4级）✅
**触发**：Playwright 动作抛定位失败异常（quick_timeout=500ms）。

**管线**：
```
试原定位符 → L1 语义(启发式预检/多定位策略链降级, 免费~0ms)
→ L2 DOM模糊匹配(rapidfuzz, 免费~50ms) → L3 AI DOM重定位(LLM, 付费~1-3s)
→ L4 视觉模型(kimi-2.6 截图多模态, 付费~2-5s) → 失败 ElementNotFoundError
```
每级命中：缓存 + 置信度+1；缓存失效：confidence-1；连续3次失败删除缓存重新自愈；confidence≥3 回写全局页面仓库（ElementService.writeback_healed_locator）。

**【V1.1变更】** L4 视觉模型确定接入：moonshot provider，model=kimi-2.6，多模态 OpenAI 兼容格式（text + image_url base64）。定位器契约已修复（返回 page.locator() 兼容表达式）。自愈未集成 playwright-healer 库（自研实现，P3）。

### 9.2 全局页面对象仓库 ✅
两级存储（页面-元素），元素必须挂页面下。写入路径：抓取入库(manual)、AI转换生成→人工确认入库(ai_generated)、自愈回写(confidence≥3, self_heal)。转换时第一优先级查询。

### 9.3 SSE 文字直播 ✅
`GET /api/stream/{session_id}`（EventSource），7 字段消息格式见 §3.1；连接保持30分钟，空闲超时5分钟，断线重连+last_event_id 续传。

### 9.4 Token 成本管理 ✅
采集点：AI 网关每次调用记录 tokens_used（prompt+completion）→ ai_call_log + token_quota。聚合：实时（当前任务）/当日（仪表盘）/趋势（近7/30天折线）/剩余/预警（剩余<10% 弹窗+横幅）。

### 9.5 幻觉/冲突检测 ✅
管线：AI生成用例 → [1]规则引擎禁用词检测（观察/验证/查看等感知动词）→ [2]前置缺失检测 → [3]与 PRD 语义比对（余弦相似度<0.6 标记逻辑矛盾）→ 标记 → 人工复核确认定稿。

---

## 第10章 数据模型（V1.1 以实现为准）

**全部表**（backend/app/models + backend/migrations）：

| 表 | 说明 |
|---|---|
| project | 项目 |
| page_repository / element_repository / fetch_history / change_detection | 元素库四表 |
| self_heal_cache | 自愈定位缓存（element_id/locator_value/confidence/hit_count/fail_count/ttl）|
| test_point / test_case / case_version | 测试点、用例、版本历史 |
| script_asset / convert_session | 脚本资产（含 category/module/last_status/run_count/last_run_at）、转换会话 |
| regression_set | 回归集关联（UNIQUE(project_id, script_id)）|
| execution_record / execution_detail | 执行记录/明细（含 heal_status/heal_log）|
| ai_call_log | AI 调用日志（model/tokens_used/stage）|
| token_quota | Token 配额（UNIQUE(project_id)）|
| knowledge_document / knowledge_chunk(pgvector 1536) / knowledge_record | 知识库三表 |
| test_rule | 测试规则（builtin 标记）|
| generation_session / hallucination_config | 生成会话、幻觉配置（代码新增，V1.0 DDL 无）|
| code_scan / code_issue | 白盒扫描/问题 |
| system_setting / test_env / operation_log | 系统设置 KV、环境、审计日志 |

**与 V1.0 DDL 的差异要点**：元素表 UNIQUE(page_id, element_id)（V1.0 为 page_id+alias）；页面表字段改名 page_url 且唯一约束需迁移补齐；test_case steps 为 JSON；ScriptAsset 扩展回归字段；knowledge_base 单表 → 三表替代。

## 第11章 API 清单（V1.1 以 routers 实现为准）

| 模块 | 前缀 | 主要端点 |
|---|---|---|
| 健康检查 | / | GET /、/ping |
| 项目 | /api/v1/projects | CRUD 5个 |
| 仪表盘 | /api/v1/dashboard | GET /overview |
| AI生成 | /api/v1/ai | upload-document、search-knowledge、knowledge-results/{sid}、identify-points、test-points(+PUT)、generate-cases、rules CRUD |
| 元素 | /api/v1/elements | fetch、import、pages(+elements/history)、DELETE、change-detection(+fix) |
| 用例 | /api/v1/test-cases | CRUD、export/import、stats、batch、versions/rollback、refine/refinement-report/apply-suggestions、review |
| 脚本 | /api/v1/scripts | convert、list/stats、run/batch-run/quick-run、detail、confirm、diagnose |
| 回归 | /api/v1/regression | list、members、identify、stats、run、latest-execution、push(桩)、report-summary |
| 报告 | /api/v1/reports | records(+details)、trend、generate、export |
| 评审 | /api/v1/reviews | stats、batch-refine、refinement-report、batch-review |
| 白盒 | /api/v1/whitescan | scan、scans(+issues)、issues PATCH/ai-fix、generate-cases、export |
| 系统 | /api/v1/system | settings、test-connection、runtime-config、envs CRUD、operation-logs、tokens status/quota/usage |
| 诊断 | /api/v1/diagnostics | analyze、apply |
| SSE | /api | stream/{session_id} GET/DELETE |

## 第12章 异常处理、部署与安全

**错误码**：沿用 V1.0 §12.1（0成功/40001参数校验/40002格式不支持/40003超限/40101-40102认证类【本期未启用】/40401资源不存在/50001数据库/50002 AI服务(重试3次)/50003执行超时/50004自愈失败/50005 Token耗尽）。

**重试策略**：AI API 3次指数退避(1s,2s,4s)超时30s；Playwright 2次间隔1s；自愈定位3次间隔500ms总超时10s；数据库3次间隔1s。

**部署环境实测（2026-09）**：PostgreSQL 16 ✅（密码 Admin@123）、Docker ✅、chromium ✅；待部署：Redis、MinIO、backend/.env（存在 `backend/.en` 疑似拼写错误待确认）。脚本在 Docker 容器内执行与平台进程隔离。

**安全**：API Key AES-256-GCM 加密存储；SQLAlchemy 参数化；CORS 当前 allow_origins=["*"]（P3 待收紧）；协议模拟数据仅本地存储（保密要求，随协议模拟排期）；操作审计 ✅。

**性能指标**：元素抓取<3s、AI用例生成<30s(10条)、脚本转换<10s(单)、脚本执行<60s(单)、报告生成<5s、自愈启发式<50ms、自愈AI<3s、数据库查询<100ms、50并发。

---

## 第13章 实现状态总表与真实化待办

### 13.1 模块实现状态

| 模块 | 状态 | 说明 |
|---|---|---|
| 元素库 | ✅ | 前端部分区块、Redis 键待补 |
| AI智能用例生成 | ✅ | 材料解析/知识注入有占位 |
| 用例评审E2E精修 | ✅ | case_refiner 部分硬编码 |
| 用例转脚本 | ✅ | 断言校验部分类型占位 |
| 用例管理 | ✅ | — |
| 执行引擎/自愈 L1-L4 | ✅ | Playwright 启动待真实化验证 |
| 回归测试 | ✅ | 推送为日志桩 |
| 执行记录与报告 | ✅ | 推送桩 |
| 白盒体检 | ✅ | 含 CodeStructureAnalyzer + 功能用例生成 |
| 知识库 RAG | ✅后端 | 前端页面 mock，真实注入待接 |
| 系统设置 | ✅ | scope 配模型待办 |
| 接口测试（解析/管理/调试/一键测试）| 🟡 | 骨架级 |
| 协议模拟 | ❌ | 未实现 |
| 登录/认证 | ❌ | 本期不做 |

### 13.2 假成功点清单（2026-09-02 扫描，集成阶段销号底账）

**P1（用户直接踩）**：知识库页整页 mock（文档列表/假删除/假重试向量化/项目下拉）；生成历史页 mock（会话列表/假删除/导出"开发中"）；报告推送链路桩（后端 notifier 仅日志，前端提示"已推送"）。

**P2（半桩）**：材料解析前端拼字符串；识别/生成后 setTimeout 盲拉非真轮询；规则管理 prompt_template 恒传 null；评审状态筛选纯前端过滤；断言校验 field_value/status_changed 占位假通过；异常路径建议硬编码；知识上下文硬编码未取库。

**P3（环境性）**：MinIO 不可用时内存降级占位 URL；CORS 通配；自愈未集成 playwright-healer；created_by=DEFAULT_USER。

### 13.3 真实化统一待办（既定策略：全模块骨架完成后统一做）
1. 统一接入大模型（填 API Key：GLM/Qwen/Moonshot kimi-2.6）+ 按 scope 配模型（ai_model_config）
2. 一次性执行数据库迁移（迁移脚本已积累于 backend/migrations/，幂等化）
3. 部署 Redis + MinIO，补 backend/.env
4. 真实 DB / 真实 Playwright / 真实 LLM 集成验证（当前 496 测试为 mock，属既定预期）
5. 假成功点按 §13.2 清单逐个销号；销号方式：先用平台自测自己（UI 自动化全流程验证），结果回填清单
