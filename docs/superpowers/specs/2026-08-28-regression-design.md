# 回归测试（模块 #8）设计

> 创建：2026-08-28
> 流程：Superpowers brainstorming → spec → writing-plans → TDD → 编码 → 审查
> 依据：需求 §3.6.4 回归测试（页面/字段/REG-01~06）、§3.6.5 回归集数据模型、§3.6.6 AI 识别六规则、§3.6.7 分类体系、§5.2 菜单与执行类型枚举、§6.1.2 SSE stage
> 需求核对：2026-08-28 双子代理核对（第一部分页面/字段/规则 + 第二部分 DDL/Redis/API/SSE/推送）结论已落入 §1.4 偏差表与 §2-§5 设计
> 模块归属：模块 #8「回归测试」。依赖全在 master：#5a（batch-run 语义/run_scripts_task）、#6（execution_record + 报告生成导出 + notifier stub）、#5c（失败行 AI 诊断）。#7（worktree 未合）/ #9（另一会话未完）与 #8 无文件冲突（#9→#8 经 test_case 间接衔接，#8 的 confirm hook 天然覆盖白盒产出）。

---

## 1. 目标与边界

### 1.1 本模块做

回归集管理（AI 识别 + 人工调整 actual_included）→ 回归批量执行（exec_type=ui_regression，失败策略可配）→ 回归报告（复用 #6 生成/导出 + #5c 失败行诊断 + notifier 推送 stub）→ 脚本库页回归三字段展示（#5a 书面推迟项落地）。

### 1.2 不做（明确留下游/后续）

| 不做项 | 归属 | 理由 |
|---|---|---|
| 真实推送渠道（钉钉/飞书/邮件） | #10 P1 | REPORT-04【联想】无报文定义；#8 用 #6 notifier stub，#10 将来补 notify 配置项 |
| AI 辅助脚本分类（§3.6.7"AI辅助归类"） | 后续切片 | 独立功能，不在 REG-01~06 验收线内；分类人工调整已支持 |
| TC-0001 用例编号展示 | #4 缺口 P1 | TestCase 无编号字段；回归列表显示脚本名即可 |
| exec_id 改 EXEC-YYYYMMDD 格式 | #5a 既有偏差 | 需求 §5.2 格式 vs 实现 exec-{session[:8]}；#8 继承不另改 |
| [回归集管理] 按钮独立形态 | 不做 | 线框图单页全区块，按钮语义模糊；其合理落点（重算识别）= POST /identify 入口 |

### 1.3 与既有模块的关系

- **#5a**：批量执行复用 run_scripts_task（Celery）+ ScriptExecutor；REG-06 结果同步脚本库已有；scripts list API 扩 include_regression 参数（#5a 书面推迟项）
- **#6**：回归执行报告块 = execution_record(exec_type=ui_regression) 摘要 + /reports/{exec_id}/generate + export；notifier stub
- **#5c**：报告块失败行 [AI诊断] 复用 /diagnostics/analyze（detail_id 直取，batch 安全）
- **#4**：confirm 端点 hook 识别（§3.6.6"脚本入脚本库后自动触发"）；convert persist 时回写 ScriptAsset.module（数据源，见偏差 J）
- **#9**：白盒产出用例经 #4 转脚本入库 → confirm hook 自动识别，无需专门接口

### 1.4 与需求的偏差

| # | 偏差 | 需求 | 本模块做法 | 理由 |
|---|---|---|---|---|
| F | exec_type 取值 | §5.2.3 枚举"UI回归" | `"ui_regression"`（小写下划线） | 对齐现有 single/batch/quick_run 风格；测试已有先例（test_report_generator.py:23）；执行记录列表可筛 |
| H | 识别触发时机 | §3.6.6"脚本入脚本库后自动触发" | hook 在 **confirm**（TRANS-02 用户确认入库） | "入库"语义模糊：convert persist 时 status=generated 未确认，confirm 才是 TRANS-02 定义的用户确认入库点；轻量同步调用无 LLM |
| R3/R4/R6 | 量化口径 | §3.6.6 只给定性描述+权重 | 口径为设计定义（见 §3.1 规则表） | 需求不可直接执行，spec 明文记录口径供验收 |
| K | max_failures 语义 | §3.6.4.3 批量执行配置"最大失败数" | 保持 #5a **步级**语义；批量级中断由 **fail_fast**（失败策略）承担 | 两个概念需求混在一字段组；不破坏 #5a 既有行为 |
| O | 推送 | REG-05"支持推送" | POST /{exec_id}/push 调 notifier.notify_report_ready（stub 日志） | 真实渠道无定义，#10 P1 |
| I | upsert 覆盖语义 | 需求未写明 | 识别 upsert 更新 ai_suggested/ai_reason，**不覆盖** actual_included（include_source=manual 的行识别不再动 actual_included） | 用户手动调整（REG-03）优先于 AI 建议 |
| J | module 数据源 | §3.6.5 有列无来源 | #4 convert persist 时从 TestCase.point_id→TestPoint.page_name 推导写入；#8 只读 | "模块代表性"规则的数据前提；写时机在 #4 路径最小侵入 |

---

## 2. 数据模型

### 2.1 新建 regression_set 表（§3.6.5 DDL 原样）

`backend/app/models/regression.py` 新建：

```python
class RegressionSet(Base):
    """回归集关联表 (§3.6.5): 脚本 ↔ 回归集成员关系 + AI 识别结果."""
    __tablename__ = "regression_set"
    __table_args__ = (
        UniqueConstraint("project_id", "script_id", name="uq_regression_project_script"),
        Index("idx_reg_project", "project_id"),
        Index("idx_reg_included", "actual_included"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True)
    script_id = Column(UUID(as_uuid=True), ForeignKey("script_asset.id", ondelete="CASCADE"), nullable=False)
    ai_suggested = Column(Boolean, default=False, comment="AI 判定是否纳入")
    ai_reason = Column(String(200), comment="AI 命中原因 (规则名拼接)")
    actual_included = Column(Boolean, default=False, comment="实际纳入 (AI建议+人工调整)")
    include_source = Column(String(10), default="ai", comment="ai/manual")
    included_at = Column(DateTime(timezone=True), server_default=func.now())
```

- DDL 按需求原样：UNIQUE(project_id, script_id) + idx_reg_project + idx_reg_included（部分索引 WHERE actual_included 在 SQLAlchemy Index 无 where 时降级为普通索引，功能等价，注明）
- 级联：project RESTRICT / script **CASCADE**（成员关系随脚本消亡，REG-01 从属语义；对比 execution_detail.script_id 的 SET NULL 是保留历史，两者各自正确）

### 2.2 exec_type 扩值（无迁移）

`execution_record.exec_type` VARCHAR(20) 无约束，加 `"ui_regression"` 值免迁移。single/batch/quick_run 保留 #5a 原语义。

### 2.3 ScriptAsset.module 回写（偏差 J）

#4 convert persist 路径（script_convert_service 落 ScriptAsset 处）：`module = TestCase.point_id→TestPoint.page_name`（JOIN 链已有）。#8 不写此列，只消费。

### 2.4 无新 Redis 键

回归批量执行复用 execution:{exec_id} / task:queue / sse:{session_id} 三键（§8.3 无回归专用键）。

---

## 3. AI 识别规则引擎（REG-02，§3.6.6）

`backend/app/services/regression_service.py` 内实现。**六规则 0-2 分制，总分 ≥3 → ai_suggested=true**，ai_reason 拼命中项（≤200 字符，风格如"P0核心用例，历史通过率稳定"）：

| # | 规则 | 权重 | 得分 | 数据源（全在 master） |
|---|---|---|---|---|
| R1 | 用例优先级 | 高 | P0=2 / P1=1 / 其他=0 | ScriptAsset.case_id → TestCase.priority（默认 P1） |
| R2 | 历史通过率 | 高 | 近 10 次（execution_detail: script_id+step=0）pass 率 ≥80% → 2；运行 <3 次 → 0（不罚） | ExecutionDetail(script_id, step=0, status, created_at) |
| R3 | 核心流程覆盖 | 中 | category∈{core_flow, ui_smoke} → 1；关联 TestPoint.type_label 含"正常"再 +1 | ScriptAsset.category + case_id→point_id→TestPoint.type_label |
| R4 | 模块代表性 | 中 | module 非空 且 该 module 下当前无 actual_included=true 的其他脚本 → 1；module 空 → 跳过 | ScriptAsset.module + regression_set JOIN |
| R5 | 运行稳定性 | 中 | 近 5 次 pass↔fail 翻转 ≥2 → flaky，0 分；否则 1 分；运行 <2 次 → 不判（0 分不罚） | ExecutionDetail 同 R2 时间序 |
| R6 | 依赖复杂度 | 低 | step_mapping 步骤数 ≤10 且去重 element_name 数 ≤8 → 1 | ScriptAsset.step_mapping |

- **新脚本（无运行数据）**：R1+R3+R6 仍可达 4 分，P0 新脚本能入集 ✓
- **识别流程**：输入 project_id → 全量 confirmed 脚本逐个打分 → upsert regression_set（冲突时更新 ai_suggested/ai_reason；actual_included 保持不动——首次识别（无行）时 actual_included=ai_suggested，include_source="ai"）
- **触发**：confirm hook（同步调，规则引擎纯 SQL 无 LLM 开销低）+ 回归页 POST /identify 手动重算
- **ai_reason 格式**：命中规则名拼接，如"P0核心用例；历史通过率92%；依赖少"（≤200 截断）

---

## 4. 后端 API（/regression 前缀，`backend/app/api/v1/regression.py`）

| 端点 | 方法 | 语义 | 需求 |
|---|---|---|---|
| /list | GET | 管理视图：project_id + category 筛选 + keyword 搜索；返回全量 confirmed 脚本 LEFT JOIN regression_set（含未纳入行）；每行含 script 信息 + ai_suggested/ai_reason/actual_included/include_source | §3.6.4.2 列表（含未纳入行） |
| /members | POST | {project_id, script_ids[], action: "add"|"remove"}；add → actual_included=true + include_source="manual"；remove → actual_included=false；upsert 兼容 | REG-03 |
| /identify | POST | {project_id} 重算全项目识别；返回 {identified, suggested_count} | REG-02 |
| /stats | GET | {total, included, passed, failed, pass_rate}——included=true ⋈ script_asset.last_status 聚合（页面加载即有值） | §3.6.4.2 统计卡 |
| /run | POST | {project_id, config{headless, timeout, max_failures, fail_fast}} → 对 included=true 全部脚本批量执行（REG-04：全部，不按勾选子集）→ 复用 run_scripts_task，exec_type="ui_regression" | REG-04 |
| /latest-execution | GET | ?script_id= → 该脚本最近一次 execution_detail(step=0) + 所属 execution_record（行内 [报告] 反查） | §3.6.4.2 行内按钮 |
| /{exec_id}/push | POST | 调 notifier.notify_report_ready(exec_id, meta)（stub 日志）→ {pushed: true} | REG-05 |
| /report-summary | GET | ?project_id= → 最近一次 exec_type=ui_regression 的 execution_record 摘要 + 失败 detail 行（内嵌报告块；失败行带 screenshot_url/script_id/detail_id 供 #5c 诊断） | §3.6.4.2 报告区 |

- **config 扩展**（偏差 K）：RunConfig 加 fail_fast: bool = False（继续默认）；script_tasks.py 消费——某脚本 detail.status=fail 后 break（步级 max_failures 逻辑不变）
- **SSE**：复用 stage="execute"（§6.1.1 枚举无回归值，记录层靠 exec_type 区分）
- **#4 hook**：confirm 端点（scripts.py）在 status→confirmed 后同步调 `RegressionService.identify_for_script(project_id, script_id)`（单脚本识别，非全量重算）

---

## 5. 前端

### 5.1 Regression.vue（新建 `frontend/src/views/Regression.vue` + 路由 `/auto/regression`）

布局按 §3.6.4.2：
1. **统计卡片**：回归集脚本数 / 通过 / 失败 / 通过率（GET /stats）
2. **回归集列表**（管理视图，GET /list）：勾选列 + 名称/状态/AI建议(tag)/是否纳入(tag)/运行次数/操作([运行][报告])；底部 [移出回归集] [加入回归集] [批量执行]（勾选驱动前两者，批量执行按 REG-04 全量）
3. **批量执行配置**：运行模式(有头/无头) / 超时(5-600) / 最大失败数(1-100) / 失败策略(继续/停止) → POST /run → SSE 订阅（复用 scriptAPI.subscribe 模式）
4. **回归执行报告块**（GET /report-summary）：总脚本/通过/失败/通过率 + 失败脚本行（[查看截图][AI诊断]→复用 DiagnosisCard + detail_id 链路 / [导出报告]→#6 export / [推送报告]→/push）
5. 行内 [运行] → scriptAPI.run；[报告] → GET /latest-execution → 跳 #6 报告详情

### 5.2 ScriptConvert.vue 加回归三列（#5a 推迟项）

scripts list API 加 `include_regression=true` 参数时 JOIN regression_set 返回 ai_suggested/ai_reason/actual_included；表格加"AI建议/是否纳入"两列（ai_reason tooltip）。

### 5.3 顺手修（与 #8 相关的既有不符）

1. `/auto/ui` 菜单空转：router 补 `{path: 'auto/ui', redirect: '/scripts'}`（菜单 index 不动）
2. `/auto/regression` 路由缺失：补路由指 Regression.vue
3. ScriptConvert.vue 分类下拉硬编码 login/smoke/regression → 改用五枚举（未分类/UI冒烟/全量回归/核心流程/接口自动化）
4. ScriptConvert.vue max_failures 上限 50 → 100（需求 1-100）

---

## 6. TRANS / REG 规则覆盖

| 规则 | #8 覆盖 |
|---|---|
| REG-01 回归集=actual_included=true | /list 过滤 + /stats 聚合口径 + /members 维护 |
| REG-02 AI 识别写 ai_suggested | 规则引擎六规则 + confirm hook + /identify |
| REG-03 手动调整 | /members add/remove（勾选批量）+ include_source=manual 优先 |
| REG-04 批量执行回归集全部脚本 | /run + exec_type=ui_regression + fail_fast |
| REG-05 报告导出与推送 | #6 export 复用 + /push stub |
| REG-06 结果同步脚本库 | #5a 已有（零代码） |

---

## 7. 测试策略（TDD，mock，核心服务 80%+）

### 7.1 规则引擎单测（重点，纯函数易测）

- 六规则逐个：R1 P0=2/P1=1/P2=0；R2 通过率阈值边界（8/10=80% 含）+ 运行<3 次不罚；R3 category 命中 + type_label 加分；R4 module 空跳过 + 已有 included 不加；R5 翻转计数（2 次翻转=flaky）+ <2 次不判；R6 步骤/元素边界
- 总分汇总：≥3 纳入 / <3 不纳入；ai_reason 拼接与 200 截断
- 新脚本（无 ExecutionDetail）路径
- **upsert 语义**：已有行 include_source=manual → 重识别不覆盖 actual_included；首次识别 actual_included=ai_suggested

### 7.2 API 测试（mock service）

- /list 管理视图含未纳入行；/members add/remove 状态机；/identify 计数返回
- /stats 聚合口径；/run 传 exec_type=ui_regression + fail_fast 进 config
- /latest-execution 反查；/push 调 notifier；/report-summary 失败行带 detail_id

### 7.3 集成点测试

- confirm hook：confirm 后 regression_set 出现识别行
- fail_fast：task 层某脚本 fail 后 break（mock executor）
- scripts list include_regression JOIN

### 7.4 前端

- vite build 过；手工验证：回归页加载/勾选加入移出/批量执行 SSE/报告块诊断跳转

---

## 8. 验收标准

1. regression_set 表按 §3.6.5 DDL 建（UNIQUE + 索引 + 级联方向正确），无迁移脚本遗留
2. 规则引擎六规则按 §3.1 口径打分，总分≥3 纳入，ai_reason ≤200 字符
3. 识别触发双路径：confirm hook 自动 + /identify 手动；upsert 不覆盖 include_source=manual 行的 actual_included
4. /members 勾选批量加入/移出（REG-03），include_source 正确
5. /run 批量执行 exec_type=ui_regression + fail_fast（失败策略停止时脚本级中断）
6. 统计卡片 = included ⋈ last_status 聚合；报告块 = 最近一次 ui_regression 执行摘要
7. 报告块失败行 [AI诊断]（走 #5c detail_id 链）+ [导出报告]（#6）+ [推送报告]（stub）
8. 行内 [运行] / [报告]（/latest-execution 反查）可用
9. ScriptConvert.vue 三列展示（#5a 推迟项）+ 分类下拉修正 + max_failures 上限 100
10. /auto/regression 路由通（菜单已有），/auto/ui 空转修复
11. 核心服务测试覆盖 ≥80%；全量回归绿

---

## 9. 未决 / 待 writing-plans 细化

- R2/R5 的 execution_detail 聚合 SQL 写法（窗口函数 vs Python 聚合——数据量小倾向 Python 聚合）
- /run 复用 run_scripts_task 时 exec_type 参数怎么传（task 签名扩参 vs 复用后 UPDATE）——倾向 task 扩可选参
- ScriptConvert.vue 三列的列宽/布局（现有表格已 7 列）
- confirm hook 同步调用的异常隔离（识别失败不应阻塞 confirm 主流程——try/except 日志）
