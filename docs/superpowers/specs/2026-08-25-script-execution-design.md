# 脚本执行引擎主干（模块 #5a）设计

> 创建：2026-08-25
> 流程：Superpowers brainstorming → spec → writing-plans → TDD → 编码 → 验收
> 依据：需求文档 §3.6.3 UI自动化测试、§9.2.4 脚本转换与执行、§10.2 用例转脚本+自愈执行流程、§8.2.7 execution_record、§4 ER 图 execution_detail；技能规则 `docs/skills-reference/testcase-to-script-skill.md`
> 需求核对：2026-08-25 派 3 子代理对照需求文档（页面/字段/规则 + API/流程/自愈 + DDL/Redis/SSE/Token）逐项核对，结论已落入本 spec。
> 模块归属：本 spec 是模块 #5「UI自动化测试执行」的第一切片（#5a 执行主干），后续 #5b（自愈 Level2-4）、#5c（AI 诊断）独立 spec。

---

## 1. 目标与边界

### 1.1 本切片做

已入库脚本（ScriptAsset）或临时粘贴脚本 → Playwright 逐步执行（乙路径）→ 失败采集（截图+DOM+堆栈）→ 写 execution_record + execution_detail → 回写 ScriptAsset(last_status/run_count/last_run_at) → SSE stage=execute 文字直播。提供 run/快速运行/批量运行/统计 端点。

自愈接入点：执行引擎在定位失败时调用 SmartLocator（已含 Level1 启发式 + semantic 自愈）。Level2-4 自愈、AI 诊断预留接口，#5b/#5c 实现。

### 1.2 本切片不做（明确留给下游）

| 不做项 | 归属 | 理由 |
|---|---|---|
| 自愈 Level2 rapidfuzz DOM 模糊 / Level3 AI DOM / Level4 视觉 | #5b | §11.1 独立状态机，单独 spec |
| 页面级 AI 诊断 `/diagnostics/analyze` + `/apply`（new_locator/confidence/apply_url） | #5c | §9.2.5 独立，打包截图+DOM+堆栈发 LLM |
| execution_record 报告聚合/导出/推送/趋势 | #6 | 模块定义即报告 |
| regression_set 表 + AI 识别纳入回归集 | #8 | §3.6.4 独立模块 |
| token_quota / ai_model_config / environment 表 CRUD + GET /tokens/status | #10 | 跨模块基建 |
| SSE last_event_id 断线续传改造 | 共享基建/#10 | 统一改造避免污染各模块 |
| 自愈回写元素库（TRANS-08 source=self_heal） | #5b | 依赖 confidence≥3，属自愈引擎 |

### 1.3 与 #4 的关系

#4 生成脚本存 ScriptAsset.content（整段代码）+ step_mapping（JSONB，当前只 {step,case_req,impl,status}）。#5a 执行走乙路径（逐步执行 step_mapping），需 step_mapping 每项含 element_name/page_name 才能查元素库。故 **#5a 扩 #4 的 step_mapping 结构**（见 §2.2），并改 #4 的 step4_generate_code 让生成时带上 element_name/page_name。

### 1.4 与需求的偏差

| 偏差 | 需求 | 本切片做法 | 理由 |
|---|---|---|---|
| convert+run 拆分 | §9.2.4 convert-and-run 合一 | #4 已拆 convert；#5a 建 run 端点 | #4 已落地，延续 |
| execution_detail 表 | 需求仅在 §4 ER 图出现字段，无 CREATE TABLE | #5a 自建 DDL | 需求遗漏，必须补 |
| 自愈 Level | §11.1 四级 | #5a 仅接入 Level1（复用 SmartLocator），Level2-4 留 #5b | 范围分切片 |
| AI 诊断 | §9.2.5 `/diagnostics/analyze` | 留 #5c | 独立 spec |

---

## 2. 数据模型

### 2.1 新建 ExecutionDetail 表（§4 ER 图，#5a 补 DDL）

`backend/app/models/execution.py` 新增：

```python
class ExecutionDetail(Base):
    """执行明细表 - 每条用例/每步的执行记录 (§4 ER 图 1:N execution_record→execution_detail)"""
    __tablename__ = "execution_detail"
    __table_args__ = (Index("idx_exec_detail_record", "execution_record_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_record_id = Column(UUID(as_uuid=True), ForeignKey("execution_record.id", ondelete="CASCADE"), nullable=False)
    script_id = Column(UUID(as_uuid=True), ForeignKey("script_asset.id", ondelete="SET NULL"))
    case_id = Column(UUID(as_uuid=True), ForeignKey("test_case.id", ondelete="SET NULL"))
    step = Column(Integer, comment="步骤序号，0=整体")
    action = Column(String(50), comment="click/fill/select/.../overall")
    status = Column(String(20), nullable=False, comment="pass/fail/skip/pending")
    error_type = Column(String(30), comment="locate_failed/timeout/assertion_failed/script_error")
    error_msg = Column(Text)
    stack_trace = Column(Text)
    screenshot_url = Column(Text, comment="失败截图 MinIO URL")
    dom_snapshot = Column(Text, comment="失败时页面 DOM")
    heal_status = Column(String(20), default="none", comment="none/healing/healed/failed (#5b 用)")
    heal_log = Column(JSONB, comment="自愈日志数组 (#5b 用)")
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now)

    def to_dict(self): ...
```

### 2.2 扩 ScriptAsset.step_mapping（改 #4 已提交代码）

step_mapping JSONB 每项从 `{step, case_req, impl, status}` 扩展为：

```json
{
  "step": 1,
  "case_req": "fill 用户名",
  "impl": "page.get_by_label(\"用户名\")",
  "status": "ok",
  "element_name": "用户名",
  "page_name": "LoginPage",
  "action": "fill",
  "value": "admin"
}
```

- element_name/page_name：执行时查元素库（ElementService.find_by_name）拿 element_data 喂 SmartLocator
- action/value：执行引擎用（fill 的值等）
- 改 #4 的 `script_pipeline._build_step_mapping` 让生成时带上这些字段（从 ActionWithLocator 取）
- **向后兼容**：旧 step_mapping（无 element_name）执行时若缺字段则该步标 skip + 记 error_type=script_error（"步骤缺 element_name，无法执行"），不崩

### 2.3 ScriptAsset.last_status 枚举收敛

`last_status` 当前自由 VARCHAR，收敛为枚举（不落 DB CHECK，仅 schema 约束）：`never_run` / `passed` / `failed` / `affected`。加到 `schemas/script.py` 的 `SCRIPT_LAST_STATUSES` 常量。

### 2.4 ScriptAsset.category 枚举

§3.6.3 分类枚举：`uncategorized` / `ui_smoke` / `full_regression` / `core_flow` / `interface_auto`。加 `SCRIPT_CATEGORIES` 常量（schema 约束，不落 DB CHECK）。

### 2.5 迁移

`backend/migrations/add_execution_detail_table.sql`：
- CREATE TABLE execution_detail + 索引（幂等）
- ScriptAsset.last_status/category 无需 ALTER（已是 VARCHAR，枚举仅在 schema 层）

---

## 3. 执行引擎（乙路径）

`backend/app/services/script_executor.py`（新建）：

### 3.1 执行编排

```python
class ScriptExecutor:
    def __init__(self, db, gateway, storage: StorageClient):
        self.db = db; self.gateway = gateway; self.storage = storage

    async def execute(self, script_asset: ScriptAsset, config: RunConfig, sse, execution_record: ExecutionRecord) -> ExecutionDetail:
        """执行单个脚本：逐步 step_mapping → SmartLocator → 断言 → 采集失败"""
        # 1. 启动 Playwright (headless=config.headless, timeout=config.timeout)
        # 2. goto target_url / 脚本起始页
        # 3. 遍历 step_mapping:
        #    - 查元素库 find_by_name(project_id, element_name) → element_data
        #    - SmartLocator(element_data).locate_and_interact(page, action, value)
        #    - 断言校验（若有 assertion）
        #    - 失败 → _collect_failure(page, step, error) → 落 ExecutionDetail
        #    - 达 max_failures → 停止
        # 4. 写 ExecutionDetail(整体 status, duration)
        # 5. 回写 ScriptAsset: last_status/run_count++/last_run_at
        # 6. SSE stage=execute 推送每步进度
```

### 3.2 失败采集（TRANS-04）

```python
async def _collect_failure(self, page, step: int, error: Exception) -> dict:
    screenshot_url = None
    dom_snapshot = None
    try:
        screenshot = await page.screenshot()
        screenshot_url = await self.storage.upload_bytes(screenshot, f"fail_{step}.png")
        dom_snapshot = await page.content()
    except Exception: pass  # 浏览器已关则跳过
    return {
        "error_type": _classify_error(error),  # locate_failed/timeout/assertion_failed/script_error
        "error_msg": str(error)[:2000],
        "stack_trace": traceback.format_exc(),
        "screenshot_url": screenshot_url,
        "dom_snapshot": dom_snapshot[:50000] if dom_snapshot else None,
    }
```

### 3.3 错误分类

```python
def _classify_error(error) -> str:
    if isinstance(error, ElementNotFoundError): return "locate_failed"
    if isinstance(error, asyncio.TimeoutError): return "timeout"
    if isinstance(error, AssertionError): return "assertion_failed"
    return "script_error"
```

### 3.4 Playwright 启动（改 playwright_service.py）

`PlaywrightService.start(headless: bool = True, timeout: int = 600)`：headless/timeout 参数化（原硬编码 headless=True）。#5a 执行引擎可独立用 PlaywrightService（按 config 注入），不复用元素抓取的实例。

> 注：元素抓取路径（elements.py）仍调 `PlaywrightService().start()` 不传参 → 默认 headless=True，行为不变，零回归。

---

## 4. API（FastAPI）

路由文件 `backend/app/api/v1/scripts.py`（#4 已建，#5a 扩展）：

```
POST /api/v1/scripts/run
  body: {script_id: uuid, config: {headless: bool, timeout: int, max_failures: int}}
  resp: {session_id, sse_url:"/api/sse/stream/{session_id}"}
  → 异步执行，写 execution_record + execution_detail，回写 script_asset

POST /api/v1/scripts/batch-run
  body: {script_ids: [uuid], config: {...}}
  resp: {session_id, sse_url}
  → 批量执行，一个 execution_record 汇总，多个 execution_detail

POST /api/v1/scripts/quick-run
  body: {script_content: str, target_url: str, headless: bool}
  resp: {session_id, sse_url}
  → 临时执行不入库，不写 script_asset，但仍写 execution_record(exec_type=quick_run) + execution_detail 供查看

GET /api/v1/scripts/stats?project_id=uuid
  resp: {total, passed, failed, never_run, pass_rate}  # 实时聚合 script_asset

GET /api/v1/scripts?project_id=&category=&keyword=&page=&page_size=
  → #4 已有 list，#5a 扩 category 筛选 + keyword 名称搜索（SCRIPT-02）
```

### 4.1 SSE（复用 SSEStream）

`stage="execute"`，`type` ∈ system/ai/cost/error。文字直播（SCRIPT-03 + §10.2）：
- `开始执行脚本：{name}`
- `第 {i}/{N} 步：{action} {element_name}`
- `第 {i} 步：✅ 通过` / `❌ 失败（{error_type}）`
- `自愈触发中...`（#5b 接入，#5a 预留 stage=self_heal）
- `执行完成：通过 {p}/{N}` + progress + tokens_used

### 4.2 Celery 任务

`backend/app/tasks/script_tasks.py`（#4 已建，#5a 扩展）：
- `run_scripts_task(session_id, script_id, config)`：查 ScriptAsset → 建 ExecutionRecord(exec_type=single, status=running) → ScriptExecutor.execute → 写 detail → 回写 script_asset → UPDATE execution_record(status, passed_count, fail_count, pass_rate, duration, tokens, finished_at)
- `batch_run_scripts_task`：循环 run，汇总到一条 execution_record
- `_CountingGateway` 累计 token（复用 #4 模式）

---

## 5. SCRIPT 规则覆盖

| 规则 | #5a 覆盖 |
|---|---|
| SCRIPT-01 转脚本入库默认未分类 | #4 已做 |
| SCRIPT-02 列表分类筛选+名称搜索 | #5a 扩 list（category + keyword） |
| SCRIPT-03 单脚本运行+回写状态/次数/时间 | #5a run 端点 + 回写 |
| SCRIPT-04 批量运行+汇总报告 | #5a batch-run 端点（报告聚合留 #6） |
| SCRIPT-05 快速运行不入库 | #5a quick-run 端点 |
| SCRIPT-06 失败截图报告+AI诊断/自愈 | #5a 采集截图（#5c 诊断 / #5b 自愈） |
| SCRIPT-07 元素变更命中→受影响高亮 | #5a 补 last_status=affected 联动（change_detection 触发时回写 script_asset） |

---

## 6. 测试策略（TDD，mock，核心服务 80%+）

### 6.1 单元测试（mock Playwright/SmartLocator/Storage）

- `script_executor.execute`：mock page + SmartLocator（成功/失败/缺 element_name 三分支）→ 断言 execution_detail 写入 + script_asset 回写 + SSE 推送
- `_collect_failure`：mock page.screenshot/content → 断言 screenshot_url/dom_snapshot/stack_trace 采集
- `_classify_error`：4 类错误 → 正确归类
- step_mapping 兼容：旧格式（无 element_name）→ 步骤 skip + error_type=script_error，不崩
- 统计聚合 `stats`：mock script_asset 列表 → 正确算 total/passed/failed/never_run/pass_rate

### 6.2 集成测试

- API：run → SSE → execution_record/detail 写入 → script_asset 回写（mock db + patch Celery + patch PlaywrightService）
- batch-run：多脚本汇总一条 execution_record
- quick-run：不入库 script_asset，写 execution_record(exec_type=quick_run)
- list 扩展：category 筛选 + keyword 搜索

### 6.3 守门测试

- playwright_service.start 接受 headless 参数（默认 True，元素抓取零回归）
- execution_detail 外键级联（execution_record 删 → detail 级联删）

---

## 7. 前端（Vue3）

扩 `frontend/src/views/ScriptConvert.vue`（#4 已建）或新建 `ScriptLibrary.vue`（§3.6.3 页面结构）：
- 统计卡片（总数/通过/失败/从未运行/通过率）
- 脚本库列表：分类筛选下拉 + 关键词搜索 + 分类(脚本数)分组
- [运行] [报告] 按钮
- 快速运行区：代码编辑器 + 被测URL + 运行模式 + 运行
- 批量运行：勾选 + 批量运行按钮 + 运行配置（headless/timeout/max_failures）
- SSE 文字直播（执行阶段）

> #5a 前端可与后端并行，先做统计卡片 + 运行/快速运行/批量运行入口，报告查看留 #6。

---

## 8. 验收标准

1. `POST /scripts/run` 执行单脚本 → SSE stage=execute 文字直播 → 写 execution_record + execution_detail → 回写 script_asset(last_status/run_count/last_run_at)
2. 逐步执行（乙路径）：每步查元素库 → SmartLocator.locate_and_interact
3. 失败采集（TRANS-04）：截图+DOM+堆栈 → MinIO → execution_detail.screenshot_url/dom_snapshot/stack_trace
4. 错误四分类正确（locate_failed/timeout/assertion_failed/script_error）
5. 批量运行：汇总一条 execution_record（SCRIPT-04）
6. 快速运行：不入库 script_asset，写 execution_record(exec_type=quick_run)（SCRIPT-05）
7. 统计卡片：实时聚合 total/passed/failed/never_run/pass_rate
8. list 支持 category 筛选 + keyword 搜索（SCRIPT-02）
9. 旧 step_mapping（无 element_name）兼容：步骤 skip 不崩
10. playwright_service headless 参数化，元素抓取零回归
11. execution_detail 外键级联
12. 核心服务测试覆盖 ≥80%
13. 自愈接入点预留（定位失败调 SmartLocator，Level2-4 留 #5b）
14. SCRIPT-07：变更检测命中 → script_asset.last_status=affected

---

## 9. 未决 / 待 writing-plans 细化

- Playwright 真实浏览器在 mock 测试环境无法跑，执行引擎单测全 mock page 对象；真实浏览器验证留全模块完成后统一真实化
- 断言校验的具体实现：step_mapping 是否含 assertion 字段？#4 的 AssertionPlan 未进 step_mapping（#4 step_mapping 只映射 actions）。#5a 执行时断言如何取？—— **#5a 决定**：step_mapping 加 assertion 字段（从 AssertionPlan 取），执行引擎在 action 后跑断言；若 step_mapping 无 assertion 则跳过断言只验证操作不报错
- target_url 来源：脚本执行起始 URL。ScriptAsset 无 target_url 字段。**#5a 决定**：run 请求体可带 target_url，或从元素库 PageRepository.page_url 推导（脚本涉及的 page_name → page_url）。先支持请求体传 target_url，自动推导留 P1
- 回归集字段（in_regression/ai_suggested）展示：归 #8，#5a list 不含这些字段
