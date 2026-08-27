# AI 诊断（模块 #5c）设计

> 创建：2026-08-27
> 流程：Superpowers brainstorming → spec → writing-plans → TDD → 编码 → 验收
> 依据：需求 §9.2.5 AI诊断与修复 API、§3.3.2 页面（[AI诊断][应用修复]）、§3.3.3 失败诊断字段组、§3.3.4 TRANS-05/06、§3.6.3.4 SCRIPT-06、§3.6.4 回归报告、§11.4 Token、§12.1/12.2 错误码与重试
> 需求核对：2026-08-27 双子代理核对（第一部分字段/规则 + 第二部分 DDL/流程/机制）结论已落入 §1.4 偏差表与 §2/§3 设计
> 模块归属：本 spec 是模块 #5「UI自动化测试执行」的第三切片（#5c AI 诊断）。#5a 执行主干、#5b 自愈 L1-4 已完成。#4 脚本级诊断（/scripts/{id}/diagnose 四分类+步骤重生成）**并存不动**。

---

## 1. 目标与边界

### 1.1 本切片做

页面级 AI 诊断：执行失败后，用户在失败明细点 [AI诊断] → 后端按 execution_id 自动取数（#5a ExecutionDetail 全套失败采集 + step_mapping 拼 script_fragment）→ 打包发多模态 LLM（kimi2.6 看截图，复用 #5b MoonshotProvider）→ 返回诊断卡 `{diagnosis, suggestion, new_locator, confidence}` → 用户点 [应用修复] → new_locator 清洗后回写元素库（source="ai_fixed"）→ 一键重跑验证（SCRIPT-06 闭环）。

### 1.2 本切片不做（明确留下游）

| 不做项 | 归属 | 理由 |
|---|---|---|
| KB-AUTO-01 诊断结果写 knowledge_record | #7 知识库 | knowledge_record 表未建（需求 DDL 有、实现无），向量采集管线未通；#5c 落库格式稳定并文档化即可 |
| 按 scope 配诊断模型（ai_model_config scope=ai_fix） | #10 待办增强 | ai_model_config 表未建；本切片路线1 硬编码 provider="moonshot"（同 #5b Level4），迁移路径已在 #10 待办登记 |
| 脚本内容更新（TRANS-06 字面「更新脚本」） | #4 调试修复已有 | 执行走元素库，改定位器才对症；#4 的步骤重生成+version+1 已覆盖脚本更新语义（§1.4 偏差 G） |
| quick-run 快速运行的诊断 | 不做 | quick-run 无 ScriptAsset/ExecutionRecord（#5a T8 fixup 决策），诊断卡无处落库、execution_id 无从取数 |
| new_locator 浏览器端验证 | 不做（登记限制） | apply 是纯后端操作无 page 上下文；只做清洗+格式校验，真实命中验证靠重跑 |

### 1.3 与既有模块的关系

- **#4**（并存）：#4 是脚本级手动诊断（手填参数、四分类、重生成步骤）。#5c 是页面级自动诊断（execution_id 取数、多模态、new_locator）。两者写同一个 `ScriptAsset.ai_diagnosis`——本切片**数组化**改造（§2.1），#4 写入处兼容。
- **#5a**：ExecutionDetail 是取数源（error_type/error_msg/stack_trace/screenshot_url/dom_snapshot/step/action）。
- **#5b**：复用 MoonshotProvider 多模态 + `_screenshot_to_b64` 压缩 + `_clean_llm_locator` 清洗。
- **#6**：报告详情页失败明细表（/reports/records/{exec_id}/details）是前端诊断入口之一。
- **#10**：诊断 LLM 调用走 gateway.chat(project_id=...) 继承 token 扣减/预警（§11.4）/ai_call_log 埋点（stage="diagnosis"）。

### 1.4 与需求的偏差

| 偏差 | 需求 | 本切片做法 | 理由 |
|---|---|---|---|
| G. apply 动作 | TRANS-06「应用修复**更新脚本**」 | 回写 ElementRepository.locator_strategies（source="ai_fixed"） | 执行链路运行时查元素库（SmartLocator→find_by_name），step_mapping 不存定位器，改库才生效；脚本更新由 #4 调试修复承担 |
| C. source 枚举 | §11.2 只有 manual/ai_generated/self_heal | 扩展 "ai_fixed" | 语义区分：self_heal=运行时自动，ai_fixed=人工确认的诊断修复；列注释同步 |
| E. confidence 语义 | 三处矛盾：§9.2.5 0-1 浮点 / §3.5 元素库 0-100 整数 / §11.1 自愈计数器 | 诊断卡存 0-1 浮点原文；apply 时元素库 confidence=round(c×10) **直接设值**（0.92→9，不叠加自愈 +1 计数器） | 对齐现有列注释 0-10 与自愈 writeback 量级 |
| A. ai_diagnosis 结构 | 需求只说「AI诊断结果 JSON」未定结构 | 数组化 [{mode:"rule"\|"multimodal", ...card}]，新卡 append，前端取最新 | #4 rule 卡与 #5c 卡共存不互覆 |
| D. 诊断模型 | §5.4.1.3「AI修复模型」下拉（P1，默认继承调试 glm-4） | 路线1 硬编码 provider="moonshot"（kimi2.6 多模态） | 需求模型是文本模型看不了截图；多模态需 kimi2.6；scope 配模型归 #10 |
| B. script_fragment | §9.2.5 请求体手填代码片段 | step_mapping[step] 拼 `{action} {impl} {value}` 近似 + 降级整段脚本 + 请求可覆盖 | ExecutionDetail 无此字段；impl 实为定位器字符串非代码行（核对确认） |
| F. quick-run 诊断 | SCRIPT-06 未区分 quick-run | quick-run 不支持诊断 | 无 ScriptAsset/ExecutionRecord 落库（#5a 决策延续） |
| 入参方式 | §9.2.5 execution_id + error_data 手填 | execution_id 自动取数为主，error_data 可选覆盖 | #5a ExecutionDetail 已存全套，前端零填参；保留覆盖能力（DOM 修复后重试场景） |

---

## 2. 数据模型

### 2.1 ScriptAsset.ai_diagnosis 数组化（无新表/无迁移）

现状：JSONB，#4 存单对象 rule 卡。改为**数组** `[{mode, ...card}]`：

```json
[
  {"mode": "rule", "category": "script_problem", "can_fix": true, "reason": "...",
   "failed_step": 3, "error_type": "locate_failed", "error_msg": "...", "suggestion": "...",
   "created_at": "2026-08-27T10:00:00Z"},
  {"mode": "multimodal", "execution_id": "...", "step": 3, "action": "click",
   "error_type": "locate_failed", "error_msg": "...",
   "diagnosis": "定位器失效，页面ID已变更为 new-login-btn",
   "suggestion": "更新定位器为 #new-login-btn",
   "new_locator": "#new-login-btn", "confidence": 0.92,
   "created_at": "2026-08-27T10:05:00Z"}
]
```

- 新诊断 **append**（保留 #4 手动诊断历史）；前端取数组最后一项展示
- **兼容**：读取时若为 dict（#4 旧单对象）包装为单元素数组；#4 写入处（scripts.py:235）同步改为 append + mode="rule"
- 时间戳来源：诊断卡由 API 层生成（datetime.utcnow isoformat），无脚本限制

### 2.2 复用 ElementRepository（apply 目标）

`locator_strategies`（JSONB）+ `source`（"ai_fixed" 新值，列注释同步为 manual/auto/healed/ai_fixed）+ `confidence`（round(c×10) 设值）。回写格式与 #5b TRANS-08 一致：`{"strategies": [{...new_strategy}]}`。

### 2.3 无新 Redis 键

§8.3 无诊断缓存/限流键；token 计数归 #10 token:counter（网关继承）。

---

## 3. 后端服务

### 3.1 DiagnosticsService（新建 `backend/app/services/diagnostics_service.py`）

```python
class DiagnosticsService:
    """页面级 AI 诊断 (#5c): execution_id 取数 → 打包 → 多模态 LLM → 诊断卡."""

    def __init__(self, db, gateway, storage):
        ...

    async def analyze(self, execution_id: str, step: Optional[int] = None,
                      override: Optional[dict] = None) -> dict:
        """TRANS-05: 打包截图+DOM+堆栈+script_fragment 发 AI 分析.
        1. ExecutionDetail 取失败步骤 (step=None 取第一个 fail 的 detail)
        2. script_fragment: ScriptAsset.step_mapping[step] 拼 "{action} {impl} {value}";
           无 step_mapping → 整段脚本; override 可覆盖任意字段
        3. 截图: storage 读 screenshot_url → base64 (复用 #5b _screenshot_to_b64 压缩)
        4. 多模态 messages (text+image_url) → gateway.chat(provider="moonshot")
        5. 解析 LLM JSON 输出 → 诊断卡 (confidence 0-1, new_locator 清洗)
        6. append ScriptAsset.ai_diagnosis + ai_call_log 埋点 (stage="diagnosis")
        """

    async def apply(self, script_id: str, new_locator: str, confidence: float,
                    element_name: Optional[str] = None) -> dict:
        """TRANS-06 偏差版: new_locator 清洗 → 回写元素库.
        1. _clean_llm_locator 清洗 (拒绝 get_by_* 表达式, 格式校验 text=/[aria]/role=/#id/xpath=)
        2. element_name 缺省时从最近诊断卡/step_mapping 推; 查 ElementRepository (find_by_name)
        3. UPDATE locator_strategies + source="ai_fixed" + confidence=round(c*10)
        4. 返回 {element_id, updated: bool, cleaned_locator}
        """
```

**LLM 输出解析**（防幻觉，#5b 审查教训）：提示词要求 LLM 输出 JSON（diagnosis/suggestion/new_locator/confidence 四字段），解析失败降级为纯文本 diagnosis + new_locator=None + confidence=None。new_locator 过 `_clean_llm_locator`（复用 self_heal_engine），非法则置 None + suggestion 注明「定位器无效，请参考建议手动修改」。

### 3.2 API（新建 `backend/app/api/v1/diagnostics.py`，挂 /diagnostics 前缀）

```
POST /api/v1/diagnostics/analyze
  请求: {execution_id: uuid, step?: int, error_data?: {error_type?, error_msg?, screenshot_url?, dom_snapshot?, script_fragment?}}
  响应: {code: 0, data: {diagnosis, suggestion, new_locator, confidence, apply_url: "/api/v1/diagnostics/apply", card: {...完整诊断卡}}}
  错误: 404 execution/detail 不存在; 400 无失败 detail; 503 gateway 未配置

POST /api/v1/diagnostics/apply
  请求: {script_id: uuid, new_locator: str, confidence: float, element_name?: str}
  响应: {code: 0, data: {element_id, updated, cleaned_locator}}
  错误: 404 元素不存在; 400 new_locator 清洗后非法
```

- §9.2.5 响应体字段全数覆盖（diagnosis/suggestion/new_locator/confidence/apply_url），另加 card 完整卡（前端展示用）
- apply_url 按需求返回路径字符串；前端实际调 apply 时传 script_id+new_locator（来自诊断卡）
- provider 路线1：`gateway.chat(messages, provider="moonshot", project_id=..., stage="diagnosis")`

### 3.3 #4 写入处兼容改造

`scripts.py:235` 的 `asset.ai_diagnosis = card` 改为 append 数组 + mode="rule" + created_at。读取兼容（dict→数组包装）放模型层 helper（ScriptAsset.diagnosis_list property），两处共用。

---

## 4. 前端

### 4.1 诊断卡组件（新建 `frontend/src/components/DiagnosisCard.vue`）

- Props：card（诊断卡对象）、applying/loading 状态
- 展示：mode 标签（规则/多模态）、diagnosis、suggestion、new_locator（代码样式）、confidence 进度条、apply_url 隐含
- 操作：[应用修复]（emit apply）、无 new_locator 时按钮禁用
- 复用场景：报告页 + 转脚本页 + （未来 #7/#8）同一组件

### 4.2 入口一：报告页失败明细（`reports/ReportDetail.vue`）

失败明细表加 [AI诊断] 操作列 → 弹 DiagnosisCard（dialog）→ 调 analyze（execution_id=当前报告 exec_id 对应的 record id，step=row.step）→ 展示卡 → [应用修复] 调 apply（script_id=row.script_id）→ 成功后提示可重跑。

### 4.3 入口二：转脚本页执行结果（`ScriptConvert.vue`）

- run/batch-run 响应已带 session_id；exec_id = `exec-{session_id[:8]}`（后端拼接规则，前端同样拼接）
- 执行完成（SSE progress≥1.0）后，失败场景拉 `/reports/records/{exec_id}/details?status=fail` 存失败行
- 执行结果区失败行加 [AI诊断]（同 4.2 交互）
- #4 现有手填诊断弹窗**保留不动**（脚本级调试场景）

### 4.4 API 封装（`frontend/src/api/diagnostics.js` 新建）

```js
export const diagnosticsAPI = {
  analyze: (payload) => axios.post('/diagnostics/analyze', payload).then(r => r.data),
  apply: (payload) => axios.post('/diagnostics/apply', payload).then(r => r.data),
}
```

---

## 5. TRANS / SCRIPT 规则覆盖

| 规则 | #5c 覆盖 |
|---|---|
| TRANS-05 失败打包发 AI 分析 | analyze：execution_id 自动取数（截图+DOM+堆栈+script_fragment 四要素齐） |
| TRANS-06 应用修复 | apply：清洗+回写元素库（偏差 G，脚本更新归 #4） |
| SCRIPT-06 失败→截图报告+AI诊断/自愈 | 截图（#5a/#6）+诊断（#5c 本切片）+自愈（#5b）三件套闭环；重跑验证 |
| §9.2.5 API 契约 | analyze/apply 端点 + 响应体字段全数覆盖 |
| ai_call_log 埋点 | gateway.chat(project_id, stage="diagnosis")，走 W10 既有 log_ai_call |

---

## 6. 测试策略（TDD，mock，核心服务 80%+）

### 6.1 单元测试（mock gateway/db/storage）

- `DiagnosticsService.analyze`：
  - 取数正确（execution_id→detail→字段映射；step=None 取第一个 fail；step 指定取对应）
  - script_fragment 拼装（有 step_mapping 拼 action/impl/value；无则整段；override 覆盖生效）
  - 截图 base64（storage 读文件→压缩复用；截图文件缺失降级无图文本诊断）
  - LLM JSON 解析（合法 JSON 四字段；非法 JSON 降级纯文本 diagnosis）
  - new_locator 清洗（get_by_* 表达式→None；非法格式→None）
  - 诊断卡 append（含 created_at/mode="multimodal"）
- `DiagnosticsService.apply`：
  - 清洗合法定位器→查元素→UPDATE（source/confidence 断言）
  - 元素不存在→返回 updated=False/404
  - confidence 映射 round(c*10)
  - 清洗拒绝 get_by_* → 400

### 6.2 API 测试

- analyze：execution_id 不存在 404；无失败 detail 400；成功 200 响应体字段齐（§9.2.5 契约）
- apply：非法 locator 400；成功回写

### 6.3 兼容测试

- ai_diagnosis 数组化：#4 旧单对象 dict 读取→包装数组不崩；#4 diagnose 端点写入后变数组 + mode="rule"；#5c analyze 后 append 不覆盖 rule 卡

### 6.4 前端

- vite build 通过
- 手工验证路径：跑一个含失败步骤的脚本 → 报告页/转脚本页 [AI诊断] → 卡展示 → [应用修复] → [重跑]

---

## 7. 验收标准

1. POST /diagnostics/analyze 收 execution_id 自动取数（TRANS-05 四要素：截图+DOM+堆栈+script_fragment）
2. 多模态 kimi2.6 诊断（provider="moonshot"，截图压缩复用 #5b），响应体含 diagnosis/suggestion/new_locator/confidence/apply_url（§9.2.5 契约）
3. LLM 输出 JSON 解析 + new_locator 清洗（拒绝 get_by_* 表达式，#5b 审查教训防幻觉）
4. POST /diagnostics/apply 清洗后回写 ElementRepository（source="ai_fixed"，confidence=round(c×10) 设值）
5. ScriptAsset.ai_diagnosis 数组化（rule/multimodal 卡共存 append，#4 兼容读取）
6. 诊断调用 ai_call_log 埋点（stage="diagnosis"）+ token 计入项目额度
7. 前端双入口：报告页失败明细 + 转脚本页执行结果区，诊断卡组件复用
8. [应用修复]→[重跑] 闭环可操作（SCRIPT-06）
9. quick-run 诊断不支持（spec §1.2 登记边界）
10. 核心服务测试覆盖 ≥80%
11. KB-AUTO-01/ai_model_config scope 不做（归 #7/#10，spec §1.2 登记）

---

## 8. 未决 / 待 writing-plans 细化

- LLM 提示词模板措辞（JSON 输出格式 few-shot）——writing-plans 定稿
- screenshot_url 文件读取路径规则（storage_client 接口确认）
- ScriptAsset.diagnosis_list property 放模型层还是 service 层（倾向模型层 to_dict 配套）
- 前端 exec_id 拼接规则（`exec-{session_id[:8]}`）是否后端在 run 响应里直接返回 exec_id 更稳（倾向后端返回，避免前端复制拼接逻辑）
