# MoonTest 已完成模块 vs 需求文档 — 缺失/不符清单

**审查日期**：2026-08-20
**审查范围**：元素库、AI智能用例生成、用例管理 三个已完成模块
**需求来源**：`docs/design-doc-raw.xml`（已抽取到 `docs/requirements_sec_*.md`）
**审查方式**：3 个并行子代理逐文件对比 + 代码直接核实

> 说明：仅列出**缺失/不符**项；已符合的需求不在此列。

---

## 一、元素库模块（§3.5 / §8.2.2-3 / §8.3 / §10.1 / §11.1-2）

### 总体结论
抓取→截图→勾选→入库 主链路骨架在，但 **入库逻辑本身已损坏**、变更检测全缺、自愈缓存全缺、三类 Redis 键全缺、前端 7 区块缺一半。

### 1. 阻断性 Bug（P0，入库会直接抛异常）
| 问题 | 位置 | 说明 |
|---|---|---|
| `batch_import_elements` 引用已删除字段 | `backend/app/services/element_service.py:105-117` | 仍用 `alias/display_text/coord_x/coord_y/locator_chain`，Task 9 改 model 后未同步。源码已 TODO 标注 BROKEN。**当前一键入库必失败。** |
| 查询引用不存在的 `TestPoint.is_deleted` | `backend/app/api/v1/ai_case_generation.py:348` | TestPoint 无 is_deleted 列，该查询会报错。 |
| 查询引用 TestCase.is_deleted（存在，正常） | `ai_case_generation.py:526` | OK |

### 2. 字段 / DDL 不符（§8.2.2 / 8.2.3 / 3.5.3）
| 需求项 | 代码现状 | 状态 |
|---|---|---|
| 页面表 `UNIQUE(project_id, url_path)` | 字段改名 `page_url`，**丢失唯一约束** | 不符 |
| 元素表 `UNIQUE(page_id, alias)` | 改为 `UNIQUE(page_id, element_id)` | 不符（alias 同页唯一是硬约束）|
| 元素置信度 0-100 | model 注释写「0-10」 | 不符 |
| 元素类型枚举 button/input/link/select/other | 抓取含 textarea，未归一为 other | 部分 |
| 定位链 JSON `{strategies:[{type,value,priority}]}` | 字段名 `locator_strategies`，格式正确 | 部分对齐 |
| 变更检测表：base/current fetch id、added/removed/modified JSON、affected_script_count | model 改为逐条 `change_type` 记录，**缺全部聚合字段** | 缺失 |

### 3. 业务逻辑 ELEM-01~07（§3.5.4）
| 编号 | 状态 |
|---|---|
| ELEM-01 页面唯一标识识别 | 部分（未提取 url path）|
| ELEM-02 入库确认页面归属 | 符合 |
| ELEM-03 5种定位策略 | 符合 |
| ELEM-04 点击截图反查最近 DOM | **缺失** |
| ELEM-05 变更检测对比历史抓取 | **缺失**（仅空 model）|
| ELEM-06 变更影响脚本标记 | **缺失** |
| ELEM-07 一键更新定位器 | **缺失**（无接口无按钮）|

### 4. Redis 缓存（§8.3）— 全缺
- `page_repo:{project_id}:{url_path}` 未实现
- `element:{page_id}:{alias}` 未实现
- `heal_cache:{element_id}` 未实现

### 5. 自愈（§11.1 / §8.2.8）— 全缺
- `self_heal_cache` 表无 model、无迁移
- 置信度衰减（命中+1/失效-1/连续3失败删除）无逻辑
- 定位器降级执行器无
- confidence≥3 回写仓库无

### 6. 前端页面结构（§3.5.2，7 区块）
| 区块 | 状态 |
|---|---|
| 项目/URL/登录区 | 符合 |
| 截图红框高亮叠加 | 缺失（仅展示原图）|
| 元素列表（含 id/定位策略）| 部分 |
| 一键入库按钮 | 符合 |
| 入库弹窗（已有页面下拉+别名编辑+策略预览）| 部分（下拉写死"新建"，无别名编辑）|
| 查看抓取历史 | 缺失 |
| 变更检测区（新增/删除/变更+影响脚本+更新定位）| 缺失 |

### 元素库 P0 补全
1. 修复 `batch_import_elements` 字段映射
2. 前端入库弹窗接已有页面下拉 + 别名编辑 + 策略预览
3. 补 `self_heal_cache` model + 迁移（§8.2.8）
4. 实现三类 Redis 键写入
5. 补齐变更检测 model 聚合字段
6. 修复 `TestPoint.is_deleted` 查询 bug

---

## 二、AI智能用例生成模块（§3.1 / §6.1 / §6.4 / §6.5 / §11.3-5）

### 总体结论
后端主干（解析/识别/生成/幻觉检测/SSE 7字段/ai_call_log 模型）已搭起，但前端缺文字直播与 7 步结构、4 规则开关与禁用词注入未做、Token 成本管理整体缺失、幻觉检测缺 PRD 语义比对与复核定稿。

### 1. 阻断性 / 关键 Bug（P0）
| 问题 | 位置 |
|---|---|
| 查询引用 `TestPoint.is_deleted`（列不存在）| `ai_case_generation.py:348` |
| SSE stage 枚举未收敛为 4 值（parse_doc/identify_point/generate_case/detect_hallucination）| `tasks/ai_case_tasks.py`，现用 fetch_knowledge/apply_rules/load_knowledge 等 |
| Token 实时推送恒传 0 | SSE 消息 tokens_used/estimated 未累计真实值 |
| 4 规则开关缺失，CASE-04 禁用词未注入 prompt | `test_case_generator.py` prompt 的 action 仍含 verify |

### 2. 前端页面结构（§3.1.2，7 步）
| 步骤 | 状态 |
|---|---|
| 步骤3 4 个规则开关（el-switch）| 缺失（现为下拉/合并步）|
| 步骤4 文字直播 SSE 区域 | **缺失**（无 EventSource 订阅）|
| 步骤5 按页面分组 + 全选反选 + 类型筛选 | 缺失（平铺表格）|
| 步骤7 用例预览幻觉标记列 | 缺失 |
| 多余的"知识库检索"独立步 | 不符（应合并/移除）|

### 3. 输入材料区（§3.1.3）
- 设计方案 / UI原型 / 需求文本 三源 — **缺失**（仅单 PRD 上传）
- "至少上传一种材料"聚合校验 — 缺失
- UI原型 .png/.jpg/.pdf 类型 — 缺失
- 文件大小 ≤10MB 前端校验 — 缺失（后端有）

### 4. 规则配置 + CASE-04（§3.1.3 / CASE-04）
| 项 | 状态 |
|---|---|
| 自动化思维规则（强制，禁用"观察/验证/查看"）| 缺失（prompt 仍含 verify）|
| 边界值分析 / 场景法覆盖 / 等价类划分 三开关 | 缺失（任务硬编码 3 条规则，缺场景法/等价类）|

### 5. 字段 / 枚举不符
| 字段 | 需求 | 代码 | 状态 |
|---|---|---|---|
| type_label | 正常/异常/边界值/等价类/场景法 | 功能/UI/性能/安全 | 不符 |
| 测试点状态 | 待勾选/已勾选/已生成用例 | pending/approved/rejected | 不符 |
| 幻觉标记 | 正常/疑似幻觉/已确认 | normal/suspected（无 confirmed 流程）| 部分 |
| 标记原因落库 | 需要 | detector 返回但 TestCase 无列 | 缺失 |

### 6. SSE 消息（§3.1.3 / §6.1）
- 7 字段齐全 ✅
- stage 枚举未收敛为 4 值 ❌
- detect_hallucination 无独立 stage 推送 ❌
- tokens_used / tokens_estimated_total 恒 0 ❌

### 7. 业务逻辑 CASE-01~08
| 编号 | 状态 |
|---|---|
| CASE-01 多材料打包分组返回 | 部分（单文件+文本）|
| CASE-02 解析→提取→分组→生成 SSE | 部分（缺提取/分组独立消息）|
| CASE-03 逐条生成 | 符合 |
| CASE-04 禁用词注入 | **缺失** |
| CASE-05 禁用词 + PRD 语义比对 | 部分（仅禁用词，无语义比对）|
| CASE-06 疑似幻觉标记 + 复核定稿 | **缺失** |
| CASE-07 进度实时推送 | 符合 |
| CASE-08 Token 实时推送 | **缺失** |

### 8. Token 成本管理（§11.4 / §6.4）— 整体缺失
- `token_usage` 表 — 缺失
- `token_quota` 表（含 alert_threshold）— 缺失
- `ai_call_log` 落库 — 模型在，**生成流程未写入**
- `GET /api/v1/tokens/status` 预警接口 — 缺失
- `Redis token:counter:{project_id}` — 缺失

### 9. 幻觉检测（§11.5 / §6.5）
- 禁用词列表 — 有（含超范围词如"确认"）
- 与 PRD 语义比对（阈值 0.6）— **缺失**（仅查元素库存在性）
- 前置缺失检测 — 缺失
- 待复核 → 确认定稿/重新生成 流转 — 缺失

### 10. DDL 对比
| 项 | 状态 |
|---|---|
| test_case steps 应 JSONB | 用 JSON |
| test_case `UNIQUE(project_id,name)` | 未声明 |
| generation_session / hallucination_config | DDL 无此二表，代码新增且未启用 |

### AI生成 P0 补全
1. 前端补文字直播 SSE 订阅 + 7 步结构
2. 4 规则开关 + CASE-04 禁用词 prompt 注入
3. 修复 `TestPoint.is_deleted` 查询 bug
4. Token 实时推送真实值
5. 前端用例预览增幻觉标记列 + 复核定稿

### AI生成 P1 补全
6. token_usage / token_quota 表 + `GET /tokens/status`
7. 幻觉 PRD 语义比对（阈值0.6）+ detect_hallucination 独立 stage
8. 输入材料区补设计方案/UI原型/需求文本 + 至少一种校验
9. test_case steps 改 JSONB + UNIQUE 约束
10. type_label / 状态枚举对齐需求

---

## 三、用例管理模块（§3.4 / §3.2 / §8.2.5-6）

### 总体结论
CRUD、筛选、分页、软删除、批量操作、步骤编辑器基础能力在，但**版本历史与回滚、导入导出、用例评审/E2E精修、自动化状态自动流转均完全缺失**，且前后端字段/枚举多处不一致，前端批量定稿调用了后端不识别的 action。

### 1. 阻断性 / 关键 Bug（P0）
| 问题 | 位置 |
|---|---|
| 前端批量定稿调用 `action:'update_status'` + `update_data`，后端不识别 | `frontend/src/views/Cases.vue:397-399`；后端只认 `finalize` |
| 用例类型枚举不符 | 后端 functional/performance/security/compatibility/usability；前端 functional/api；需求只要 功能/接口 |
| 自动化状态枚举不符 | 后端 pending/automated/cannot_automate；前端 none/partial/full；需求 未转化/已自动化/部分自动化 |
| 步骤结构前后端不一致 | 前端 {step_number,action,expected,data}；后端 {seq,action,target,data,expected}；需求 [{step,action,expected}] |
| 前端字段名 title，后端字段名 name | CaseForm 用 title |
| 前端 preconditions，后端 precondition | CaseForm 用 preconditions |

### 2. 页面结构（§3.4.2）
| 区块 | 状态 |
|---|---|
| 项目/模块/优先级/状态 筛选 | 部分（无"模块"筛选）|
| [+新建用例][导入][导出][批量删除] 按钮 | 缺失（无导入/导出）|
| 用例列表 + 分页 | 符合 |
| 版本历史（点击展开）| **缺失** |

### 3. 用例字段（§3.4.3）
| 字段 | 状态 |
|---|---|
| 用例名称同项目唯一 | 部分（无 UNIQUE 约束）|
| 关联测试点ID 必须存在 | 部分（弱关联可空，无存在校验）|
| 优先级 P0-P3 | 符合 |
| 用例类型 功能/接口 | 不符（枚举过多）|
| 自动化状态 未转化/已自动化/部分自动化 | 不符 |
| 前置条件 0-500 | 部分（无长度约束）|
| 测试步骤JSON 每步≤200 含动作动词 | 部分（上限 500，无动词校验）|
| 预期结果 0-200 | 符合 |
| 是否定稿/版本号/创建人/创建时间/更新时间 | 符合 |

### 4. 业务规则 CASE-MGMT-01~04
| 编号 | 状态 |
|---|---|
| CASE-MGMT-01 软删除保留30天 | 部分（软删除有，无定时清理）|
| CASE-MGMT-02 版本历史 diff + 回滚 | **缺失**（仅 version 整数自增）|
| CASE-MGMT-03 导入 .xlsx/.csv/.md 导出 .xlsx/.json/.xmind | **缺失**（无端点无按钮）|
| CASE-MGMT-04 自动化状态自动流转 | **缺失**（仅手工批量设置）|

### 5. 用例评审 / E2E精修（§3.2，需求标注 P0）
全部缺失：
- 评审状态（待评审/已通过/需修改）
- 评审意见（0-500）
- 可行性等级（完全自动化/部分自动化/需手工执行）
- 不可自动化原因（0-200）
- 精修报告（JSON）
> 注：设计文档 §14 曾把评审划二期，但需求 §3.2 是 P0，存在优先级偏差。

### 6. 批量操作
| 项 | 状态 |
|---|---|
| 批量定稿 | 部分（前端 action 名错）|
| 批量删除 | 符合 |
| 批量设置优先级 | 部分（后端有，前端无入口）|
| 批量设置幻觉状态 | 部分（后端有，前端无入口）|

### 7. DDL 对比（§8.2.5）
| 项 | 状态 |
|---|---|
| `UNIQUE(project_id, name)` | 未声明 |
| `idx_test_case_project` / `idx_test_case_automation` | 未声明 |
| steps JSONB | 用 JSON |
| automation_status 枚举对齐 | 不符 |
| ScriptAsset 多出 category/module/last_status/run_count/last_run_at | 超出 §8.2.6（需登记或对齐）|

### 用例管理 P0 补全
1. 版本历史：case_version 表 + diff + 回滚 API + 详情页面板（CASE-MGMT-02）
2. 导入导出：import(.xlsx/.csv/.md)/export(.xlsx/.json/.xmind) 端点 + 前端按钮（CASE-MGMT-03）
3. 用例评审字段：review_status / review_comment / feasibility_level / cannot_automate_reason / refinement_report（§3.2）
4. `UNIQUE(project_id,name)` + 索引 + steps 改 JSONB
5. 前后端字段/枚举统一：自动化状态三态、用例类型、步骤结构、title↔name、precondition↔preconditions
6. 修复前端批量定稿 action

### 用例管理 P1 补全
7. 软删除 30 天定时清理
8. 自动化状态自动流转接入脚本生成/执行模块
9. 前端补"批量设置优先级""批量设置幻觉状态"入口
10. 步骤校验补 ≤200 与动作动词

---

## 四、跨模块共性缺失（影响三个模块）

| 共性缺失 | 需求依据 | 影响模块 |
|---|---|---|
| Redis 缓存键体系（page_repo/element/heal_cache/sse/token:counter）| §8.3 | 元素库、AI生成 |
| Token 成本管理（token_usage/quota + /tokens/status）| §11.4 / §6.4 | AI生成（用例管理消费预警）|
| 自愈引擎（self_heal_cache + 置信度衰减 + 降级执行器）| §11.1 / §8.2.8 | 元素库（执行模块未建，暂前置欠账）|
| SSE stage 枚举统一 + 断线重连 + last_event_id 续传 | §6.1 / §11.3 | AI生成、元素库 |
| 字段/枚举前后端全栈统一 | §3.1/3.4/3.5 各字段 | 三个模块均有 |

---

## 五、补全优先级总表（建议执行顺序）

### P0（阻断主流程 / 必修 Bug）
1. 修复元素库 `batch_import_elements` 字段映射（入库当前必崩）
2. 修复 `TestPoint.is_deleted` 查询 bug
3. 修复用例管理前端批量定稿 action 名
4. 前后端字段/枚举/步骤结构全栈统一（三个模块）
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

**审查完成。** 以上为需求文档对照下三个已完成模块的全部缺失/不符项，已逐条核实代码。
