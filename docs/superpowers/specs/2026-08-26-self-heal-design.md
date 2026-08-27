# 自愈引擎 Level2-4（模块 #5b）设计

> 创建：2026-08-26（2026-08-27 更新：审查修复后定位器契约统一为选择器字符串）
> 流程：Superpowers brainstorming → spec → writing-plans → TDD → 编码 → 验收
> 依据：需求文档 §11.1 自愈引擎详细设计、§11.2 硬性规则、§8.2.8 self_heal_cache、§8.3 heal_cache:{element_id}、§10.2 流程、§3.3.4 TRANS-07/08；技能规则 `docs/skills-reference/testcase-to-script-skill.md`
> 需求核对：2026-08-25 模块 #5 整体核对（3 子代理）结论已落入；本 spec 聚焦自愈 Level2-4。
> 模块归属：本 spec 是模块 #5「UI自动化测试执行」的第二切片（#5b 自愈），#5a 执行主干已完成，#5c AI 诊断独立 spec。

> **定位器契约（2026-08-27 审查修复后定案）**：各级自愈返回**选择器字符串**（CSS/XPath/`text=`/`role=` 引擎语法，如 `text="登录"`、`[aria-label="用户名"]`、`role=button[name="登录"]`），与主路径 locator_strategies 的 value 格式一致，可直接传 `page.locator()`。**禁止** `page.get_by_*(...)` Python API 表达式（`page.locator()` 不认，真实浏览器抛 Unknown engine）。LLM 输出经 `_clean_llm_locator` 清洗（markdown 围栏/杂讯/引号，拒绝 get_by_* 表达式）。真浏览器守门测试 `test_self_heal_real_browser.py`。

---

## 1. 目标与边界

### 1.1 本切片做

定位失败时逐级自愈：**Level1 启发式（semantic，#1 已建）→ Level2 DOM 模糊匹配（rapidfuzz，新建）→ Level3 AI DOM（LLM，新建）→ Level4 视觉（kimi2.6 多模态截图识别，新建）**。每级命中：confidence+1 + 回写缓存；confidence≥3 时回写元素库（TRANS-08 接通，当前 helper 已写但无调用方）。全失败抛 ElementNotFoundError。透明接入 SmartLocator，ScriptExecutor 无需改。

### 1.2 本切片不做（明确留下游/后期）

| 不做项 | 归属 | 理由 |
|---|---|---|
| 自愈策略配置（SMART/HEURISTIC_ONLY/DOM_ONLY/VISUAL_ONLY/FULL/PARALLEL） | #10 | §11.1 提到，#5b 先用默认 FULL（逐级），策略开关 + UI 归 #10 系统设置 |
| 双 TTL 缓存（稳定 30 天/失效 1 小时） | 优化 | 当前固定 1 天（HEAL_CACHE_TTL=86400）够用，双 TTL 留优化，不阻断 |
| SelfHealCache 表结构改字段名 | 不改 | 需求 §8.2.8 原始字段（locator_value/hit_count/fail_count/ttl_days）与实现（healed_locator/success_count/failure_count）有偏差，改表有迁移风险，#5b 不动，spec §1.4 登记偏差 |
| 页面级 AI 诊断 `/diagnostics/analyze` | #5c | 独立 spec，打包截图+DOM+堆栈发 LLM 给 new_locator |

### 1.3 与 #5a 的关系

#5a 的 ScriptExecutor 定位失败时 SmartLocator.locate_and_interact 抛 ElementNotFoundError。#5b **改 SmartLocator 内部自愈链**（`_self_heal_and_interact` 从「只调 _heal_by_semantic」改为「调 SelfHealEngine.heal() Level1-4」），ScriptExecutor 无感知——自愈透明。ExecutionDetail.heal_status/heal_log（#5a 预留字段）由 SmartLocator 回传 heal 信息填充。

### 1.4 与需求的偏差

| 偏差 | 需求 | 本切片做法 | 理由 |
|---|---|---|---|
| Level4 视觉模型 | §11.1 四级 | **本期实现**（T8）：截图→kimi2.6 多模态 LLM→定位器，显式 `provider="moonshot"`（路线1，其他仍 glm5.2） | 有现成 kimi2.6 多模态模型，Level4 一起做更完整；按 scope 配模型留 #10 后续 |
| 策略配置 | §11.1 SMART/HEURISTIC_ONLY/... | 默认 FULL 逐级，开关留 #10 | 策略 UI + 配置归系统设置 |
| SelfHealCache 字段名 | §8.2.8 locator_value/hit_count/fail_count/ttl_days | 不改表，用现有 healed_locator/success_count/failure_count | 改表迁移风险，现有字段功能等价 |
| 双 TTL | §11.1 稳定 30d/失效 1h | 固定 1 天 | 优化项，不阻断 |
| 回写 source | §11.2 source=self_heal | 用 source="healed"（与 change_detection 一致） | 复用现有 source 取值 |

---

## 2. 数据模型

### 2.1 复用 SelfHealCache（不改表）

`backend/app/models/element.py` 的 `SelfHealCache`（字段：healed_locator JSONB / heal_strategy / success_count / failure_count / original_locator / last_used_at）。#5b 只**新增 heal_strategy 取值**：
- `semantic`（Level1，现有）
- `dom_fuzz`（Level2，新）
- `ai_dom`（Level3，新）
- `visual`（Level4，新，kimi2.6 多模态）

### 2.2 复用 ElementCacheService

`record_heal_success(element_id, healed_locator)` / `record_heal_failure(element_id)` / `should_writeback_to_repo(element_id)` / `get_writeback_locator(element_id)` —— 全部已建（#1），#5b 接通调用方。

### 2.3 ExecutionDetail.heal_status / heal_log（#5a 预留）

#5b 执行期填充：
- `heal_status`：none → healing → healed（成功）/ failed（全失败）
- `heal_log`：JSONB 数组 `[{level, strategy, success, locator?, confidence, timestamp}]`（实现：locator 已含；confidence 由缓存统一记，不重复落 log；timestamp 无时钟注入，spec §8 允许省略）
- `heal_status` 实现：none（无自愈尝试）→ healed（有自愈成功）/ failed（有自愈尝试全失败，审查 #3）

SmartLocator.locate_and_interact 返回值扩展带 heal 信息，ScriptExecutor 捕获后填 ExecutionDetail。

### 2.4 迁移

无新表/新列。SelfHealCache.heal_strategy 是 VARCHAR 自由值，加取值不需 ALTER。无迁移脚本。

---

## 3. 自愈引擎

新建 `backend/app/services/self_heal_engine.py`：

### 3.1 状态机编排

```python
class SelfHealEngine:
    """自愈引擎 Level1-4 状态机.
    Level1 复用 SmartLocator._heal_by_semantic; Level2 rapidfuzz DOM 模糊; Level3 AI DOM; Level4 视觉 (kimi2.6 多模态).
    每级命中: record_heal_success + confidence+1 + 检查回写; 失败: record_heal_failure + 降级.
    全失败抛 ElementNotFoundError."""

    def __init__(self, gateway, element_cache: ElementCacheService):
        self.gateway = gateway
        self.element_cache = element_cache

    async def heal(self, page, element_data: dict, action: str, **kw) -> dict:
        """逐级自愈, 返回 {success, locator, strategy, heal_log}."""
        heal_log = []
        # Level1: semantic (调 SmartLocator 的 _heal_by_semantic 逻辑)
        loc = await self._heal_by_semantic(page, element_data)
        heal_log.append({"level": 1, "strategy": "semantic", "success": loc is not None})
        if loc:
            await self._on_heal_success(element_data, loc, "semantic")
            return {"success": True, "locator": loc, "strategy": "semantic", "heal_log": heal_log}
        # Level2: dom_fuzz (rapidfuzz)
        loc = await self._heal_by_dom_fuzz(page, element_data)
        heal_log.append({"level": 2, "strategy": "dom_fuzz", "success": loc is not None})
        if loc:
            await self._on_heal_success(element_data, loc, "dom_fuzz")
            return {"success": True, "locator": loc, "strategy": "dom_fuzz", "heal_log": heal_log}
        # Level3: ai_dom (LLM)
        loc = await self._heal_by_ai_dom(page, element_data)
        heal_log.append({"level": 3, "strategy": "ai_dom", "success": loc is not None})
        if loc:
            await self._on_heal_success(element_data, loc, "ai_dom")
            return {"success": True, "locator": loc, "strategy": "ai_dom", "heal_log": heal_log}
        # Level4: visual (kimi2.6 多模态, provider="moonshot")
        loc = await self._heal_by_visual(page, element_data)
        heal_log.append({"level": 4, "strategy": "visual", "success": loc is not None})
        if loc:
            await self._on_heal_success(element_data, loc, "visual")
            return {"success": True, "locator": loc, "strategy": "visual", "heal_log": heal_log}
        # 全失败
        await self._on_heal_failure(element_data)
        return {"success": False, "locator": None, "strategy": None, "heal_log": heal_log}

    async def _on_heal_success(self, element_data, locator, strategy):
        eid = element_data.get("element_id")
        if eid:
            await self.element_cache.record_heal_success(eid, {"type": "healed", "value": locator, "strategy": strategy})
            # TRANS-08: confidence≥3 回写元素库
            if await self.element_cache.should_writeback_to_repo(eid):
                wb = await self.element_cache.get_writeback_locator(eid)
                if wb:
                    await self._writeback_to_repo(eid, wb)

    async def _on_heal_failure(self, element_data):
        eid = element_data.get("element_id")
        if eid:
            await self.element_cache.record_heal_failure(eid)
```

### 3.2 Level2 DOM 模糊匹配（rapidfuzz）

```python
    async def _heal_by_dom_fuzz(self, page, element_data: dict) -> Optional[str]:
        """扫页面可交互元素, rapidfuzz 算文本/属性相似度, top-K 验证."""
        from rapidfuzz import fuzz
        # 目标 = [element_name, semantic.text] 各算一次取最高分 (避免拼接稀释相似度)
        targets = [t for t in [element_name, sem_text] if t]
        selectors = ["button", "a", "input", "select", "textarea", "[role='button']", "[role='link']", "[role='checkbox']"]
        candidates = []
        for sel in selectors:
            els = await page.query_selector_all(sel)
            for el in els:
                text = (await el.text_content() or "").strip()
                aria = await el.get_attribute("aria-label") or ""
                label = await el.get_attribute("placeholder") or ""
                for field, candidate_text in [("text", text), ("aria", aria), ("placeholder", label)]:
                    if candidate_text:
                        score = max(fuzz.ratio(t, candidate_text) for t in targets)
                        if score >= 70:  # 阈值
                            candidates.append((score, el, field, candidate_text))
        candidates.sort(key=lambda x: x[0], reverse=True)
        for score, el, field, cand in candidates[:5]:  # top-5 验证
            try:
                if await el.is_visible():
                    # 按命中属性构造选择器: text→text="x" / aria→[aria-label="x"] / placeholder→[placeholder="x"]
                    return self._build_locator_from_candidate(field, cand)
            except Exception:
                continue
        return None
```

### 3.3 Level3 AI DOM（LLM）

```python
    async def _heal_by_ai_dom(self, page, element_data: dict) -> Optional[str]:
        """DOM 片段 + 元素描述发 LLM, 返回定位器, 验证."""
        dom = await page.content()
        dom = dom[:20000]  # 截断防 token 爆
        prompt = f"""页面 DOM 如下, 找到元素 "{element_data.get('element_name')}" 的 Playwright 定位器.
元素语义: {element_data.get('semantic_info', {})}
{LOCATOR_OUTPUT_INSTRUCTION}  # 要求输出选择器字符串, 禁 page.get_by_* 表达式

DOM:
{dom}"""
        resp = await self.gateway.chat([{"role": "user", "content": prompt}])
        locator = self._clean_llm_locator(resp.get("content"))  # 清洗围栏/杂讯/引号, 拒绝 get_by_*
        # 验证定位器有效
        try:
            loc = page.locator(locator)
            await loc.wait_for(state="visible", timeout=3000)
            return locator
        except Exception:
            return None
```

### 3.4 Level4 视觉（kimi2.6 多模态）

```python
    async def _heal_by_visual(self, page, element_data: dict) -> Optional[str]:
        """截图发 kimi2.6 多模态 (provider=moonshot), LLM 看图返回定位器, 验证.

        路线1: Level4 专用 kimi2.6 (显式 provider="moonshot"), 其他级仍默认 glm5.2.
        截图压缩: 超宽 (>1280px) 缩放 + JPEG q70, 控制多模态 token 成本 (审查 #6).
        """
        screenshot = await page.screenshot()
        img_b64 = self._screenshot_to_b64(screenshot)  # PIL 缩放/JPEG, 失败降级原样
        prompt_text = f"页面截图如下, 找到元素 \"{element_data.get('element_name')}\" 的 Playwright 定位器. {LOCATOR_OUTPUT_INSTRUCTION}"
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]}
        ]
        resp = await self.gateway.chat(messages, provider="moonshot")
        locator = self._clean_llm_locator(resp.get("content"))  # 清洗, 同 Level3
        # 验证定位器有效 (同 Level3)
        try:
            loc = page.locator(locator)
            await loc.wait_for(state="visible", timeout=3000)
            return locator
        except Exception:
            return None
```

### 3.5 TRANS-08 回写元素库

```python
    async def _writeback_to_repo(self, element_id, healed_locator):
        """confidence≥3 回写 ElementRepository (source=healed)."""
        # 调 ElementService.writeback_healed_locator (新建方法)
        # UPDATE ElementRepository SET locator_strategies=..., source='healed', confidence=... WHERE element_id=...
```

新建 `ElementService.writeback_healed_locator(element_id, healed_locator)` 方法（UPDATE ElementRepository，source="healed"）。

### 3.6 SmartLocator 接入

改 `SmartLocator._self_heal_and_interact`（`backend/app/services/smart_locator.py`）：
- 当前：只调 `self._heal_by_semantic`
- 改为：调 `SelfHealEngine(self.gateway, ElementCacheService).heal(page, self._element_data_dict(), action, **kw)`
- 返回值带 heal_log，SmartLocator 透传给调用方（ScriptExecutor 填 ExecutionDetail.heal_log）
- 全失败：抛 `ElementNotFoundError(msg, heal_log=...)`（异常携带失败记录，供执行器落库，审查 #3）；**不再**在 SmartLocator 里重复 record_heal_failure（引擎已记，审查 #2）

SmartLocator 需持 gateway 引用（当前不持有）——改 SmartLocator 构造或 _self_heal_and_interact 接收 gateway。

> **接入方式选择**：为减少对 #5a ScriptExecutor 的改动，SelfHealEngine 由 SmartLocator 内部构造（SmartLocator 需 gateway）。或 ScriptExecutor 构造 SelfHealEngine 传入 SmartLocator。**推荐前者**（自愈封装在 SmartLocator 内，执行器无感知）。SmartLocator 加 gateway 注入（执行器已持 gateway，传入即可）。

---

## 4. API

#5b **无新 API**——自愈在执行期透明触发。SCRIPT-06 的"运行失败触发 AI 诊断/自愈"中，自愈部分由 #5b 内化，AI 诊断端点归 #5c。

---

## 5. TRANS 规则覆盖

| 规则 | #5b 覆盖 |
|---|---|
| TRANS-07 定位失败触发自愈 | #5b Level1-4 状态机（SmartLocator._self_heal_and_interact 接 SelfHealEngine）|
| TRANS-08 自愈成功置信度≥3 回写仓库 | #5b _writeback_to_repo 接通（should_writeback + get_writeback + ElementService.writeback）|

---

## 6. 测试策略（TDD，mock，核心服务 80%+）

### 6.1 单元测试（mock page + LLM + ElementCacheService）

- `SelfHealEngine.heal`：Level1 命中（semantic 成功）/ Level2 命中（dom_fuzz 成功，Level1 失败）/ Level3 命中（ai_dom 成功，Level1-2 失败）/ Level4 命中（visual 成功，Level1-3 失败）/ 全失败（抛 ElementNotFoundError）五分支
- `_heal_by_dom_fuzz`：mock page.query_selector_all 返回候选元素列表，rapidfuzz 算分，断言取 score≥70 的 top-5 验证
- `_heal_by_ai_dom`：mock gateway.chat 返回定位器，验证 wait_for → 命中；LLM 返回无效定位器 → None
- `_heal_by_visual`：mock page.screenshot + gateway.chat(provider="moonshot") 多模态返回定位器 → 命中；无效定位器 / 截图失败 → None
- `_on_heal_success`：mock record_heal_success + should_writeback=True → 断言 _writeback_to_repo 被调
- `_on_heal_failure`：mock record_heal_failure
- `_writeback_to_repo`：mock ElementService.writeback_healed_locator 被调

### 6.2 集成测试

- SmartLocator.locate_and_interact 定位失败 → 触发 SelfHealEngine（mock）→ Level2 命中 → 返回 success + heal_log
- ScriptExecutor 执行：定位失败 → SmartLocator 自愈成功 → ExecutionDetail.heal_status="healed" + heal_log 填充

### 6.3 守门测试

- 自愈全失败 → 抛 ElementNotFoundError（不被吞）
- 回写仅在 confidence≥3 时触发（should_writeback 门槛）

### 6.4 依赖

- `rapidfuzz` 加到 `backend/requirements.txt`（纯 Python，无 C 编译）

---

## 7. 验收标准

1. 定位失败 → SmartLocator 触发 SelfHealEngine Level1-4 逐级（TRANS-07）
2. Level2 rapidfuzz DOM 模糊匹配命中候选（score≥70，top-5 验证）
3. Level3 AI DOM（LLM 返回定位器 + 验证）
4. 每级命中：record_heal_success + confidence+1 + heal_log 记录
5. 全失败：record_heal_failure + 抛 ElementNotFoundError（不被吞）
6. confidence≥3 → 回写 ElementRepository（source=healed）（TRANS-08 接通）
7. ExecutionDetail.heal_status（none/healing/healed/failed）+ heal_log 填充
8. SmartLocator 透明接入，ScriptExecutor 无需改业务逻辑（仅填 heal 字段）
9. 核心服务测试覆盖 ≥80%
10. rapidfuzz 依赖加入 requirements.txt
11. Level4 视觉自愈已实现（T8）：截图→kimi2.6 多模态→定位器→验证，显式 `provider="moonshot"`（路线1，其他级仍 glm5.2）

---

## 8. 未决 / 待 writing-plans 细化

- SmartLocator 注入 gateway 的方式（构造参数 vs 方法参数）——writing-plans 细化，倾向构造参数
- `_heal_by_dom_fuzz` 的 selector 列表 + 阈值（70）+ top-K（5）——可调，先硬编码
- `_heal_by_ai_dom` 的 DOM 截断长度（20000）——防 token 爆，可调
- Level1 semantic 复用：是调 SmartLocator 现有 `_heal_by_semantic` 还是把逻辑搬到 SelfHealEngine——倾向复用（调 SmartLocator 方法），避免重复
- heal_log 时间戳：无 Date.now（脚本限制），用 step 序号或 None
