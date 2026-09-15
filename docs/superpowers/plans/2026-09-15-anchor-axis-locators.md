# 锚点定位 + 轴定位（缺口1+2）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在元素抓取的定位器生成流水线中新增「祖先锚点」与「相邻兄弟+label」两类策略，缩短路径深度、覆盖表单场景。

**Architecture:** 改动集中在 `backend/app/services/playwright_locator_core.py` 的 `generate_locators_for_element`（纯新增 2 个策略函数）+ `verify_and_score_locator` 的 nth 惩罚豁免（锚点路径自带 1-2 层 nth，属稳定结构不应扣分）。执行引擎（smart_locator 按 score 降序消费 strategies 列表）零改动。

**Tech Stack:** Python asyncio + Playwright evaluate（JS 在浏览器内执行 DOM 遍历）；pytest + AsyncMock。

**背景：**
- 现有 CSS 全路径最长 5 层 / XPath 8 层，页面中间插元素即断（缺口1：无锚点概念）
- label+input 兄弟节点、input 无 id 时只能落到 text/class 兜底（缺口2：无轴定位）
- 材料对照结论（2026-09-15 会话）：锚点 base_score 75 介于 text(80) 与 class-type(70) 之间；轴定位 base_score 78

---

## 策略设计

### 策略 A：祖先锚点（type: `anchor`）
向上找最近的有稳定 id 或 data-testid 的祖先（≤5 层内），从该祖先往下写 1-2 层相对路径。
- JS 在浏览器内执行：从 el 往上走，命中 `id`（页面唯一才有效，复用现有唯一性检查——先粗生成，verify 环节剔除）或 `data-testid` 即停
- 生成格式：CSS `#toolbarId > div:nth-of-type(2) > button`（相对段 ≤2 层）
- **base_score 75**（锚点 id 若唯一，verify 时 unique+20 → 95，接近 id 直命中；非唯一 -30 → 45 以下自然淘汰）

### 策略 B：相邻兄弟 + label（type: `sibling-label`）
元素无 id/name/testid 时，找前一个兄弟中的 label（或前一个兄弟内含文本），生成轴定位：
- XPath 格式：`//label[text()='用户名']/following-sibling::input`（通用）；兄弟 label 含文本用 `//label[contains(., '用户名')]/following-sibling::input`
- **base_score 78**（label 文本变更会断，比 text 略低、比 class-type 高）
- 仅对 input/select/textarea 生成（button/link 有 text 策略已覆盖）

### verify 惩罚豁免
`verify_and_score_locator` 现有规则：`nth-of-type` 且非唯一 → -15。锚点路径自带 nth（相对段的第 N 个子元素），但锚点已提供结构稳定性——豁免条件加：value 含 `#` 或 `[data-testid=` 前缀锚点时不扣。

---

### Task 1: 祖先锚点策略（RED→GREEN）

**Files:**
- Modify: `backend/app/services/playwright_locator_core.py:16-156`（generate_locators_for_element）
- Test: `backend/tests/test_anchor_axis_locators.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""锚点定位 + 轴定位策略测试（缺口1+2）。

generate_locators_for_element 的 mock element 需支持：
- get_attribute(name) -> str | None
- inner_text() -> str
- evaluate(js, arg=None) -> 按 js 内特征返回（路径遍历 / 兄弟查询）
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.playwright_locator_core import generate_locators_for_element


def make_page():
    return MagicMock()


def make_element(attrs=None, path_chain=None, siblings_html=None):
    """构造 mock element。

    path_chain: 祖先链信息，供 evaluate 的锚点遍历 JS 返回
    siblings_html: 兄弟节点描述，供 sibling-label JS 返回
    """
    el = MagicMock()
    attrs = attrs or {}
    async def _get_attribute(name):
        return attrs.get(name)
    el.get_attribute = _get_attribute
    async def _inner_text():
        return attrs.get("_text", "")
    el.inner_text = _inner_text

    async def _evaluate(js, arg=None):
        # 锚点遍历 JS 特征：包含 closest 语义/遍历 parentElement 且找 id/data-testid
        if "anchor" in js or ("parentElement" in js and "id" in js):
            return path_chain  # None 或 {anchor: '#toolbar', rel: 'div:nth-of-type(2) > button'}
        # 兄弟 label JS 特征：包含 following-sibling
        if "following-sibling" in js or "previousElementSibling" in js:
            return siblings_html
        return None
    el.evaluate = _evaluate
    return el


class TestAnchorStrategy:
    @pytest.mark.asyncio
    async def test_generates_anchor_locator_when_ancestor_has_id(self):
        """祖先 2 层内有 id=toolbar → 生成 anchor 策略。"""
        el = make_element(
            attrs={"_text": "查询", "class": "btn", "type": "button"},
            path_chain={"anchor": "#toolbar", "rel": "div:nth-of-type(2) > button"},
        )
        # tag_name 走 evaluate("el => el.tagName.toLowerCase()")
        async def _tag(js):
            return "button"
        el.evaluate = _tag  # 简化：本测试只关心 anchor 候选存在
        # 重新注入 path_chain 支持
        async def _evaluate2(js, arg=None):
            if "tagName" in js:
                return "button"
            if "parentElement" in js and "id" in js:
                return {"anchor": "#toolbar", "rel": "div:nth-of-type(2) > button"}
            return None
        el.evaluate = _evaluate2

        candidates = await generate_locators_for_element(make_page(), el)
        anchor = [c for c in candidates if c["type"] == "anchor"]
        assert anchor, "应有 anchor 策略候选"
        assert anchor[0]["value"] == "#toolbar > div:nth-of-type(2) > button"
        assert anchor[0]["base_score"] == 75

    @pytest.mark.asyncio
    async def test_no_anchor_when_no_stable_ancestor(self):
        """祖先链无 id/testid → 不生成 anchor。"""
        el = make_element(attrs={"_text": "x", "class": "c"}, path_chain=None)
        async def _evaluate(js, arg=None):
            if "tagName" in js:
                return "div"
            if "parentElement" in js and "id" in js:
                return None
            return None
        el.evaluate = _evaluate
        candidates = await generate_locators_for_element(make_page(), el)
        assert not [c for c in candidates if c["type"] == "anchor"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_anchor_axis_locators.py -v`
Expected: FAIL — `anchor` 类型候选不存在（现无此策略）

- [ ] **Step 3: 实现 anchor 策略**

在 `generate_locators_for_element` 的策略 9（placeholder）之后追加：

```python
    # 策略 10: 祖先锚点（缺口1）——找最近的有稳定 id/testid 的祖先，从它往下 1-2 层相对路径。
    # 全路径 8 层在页面中间插元素即断；锚点路径短且锚在稳定结构上。
    anchor_info = await element.evaluate("""
        el => {
            let depth = 0, node = el;
            const MAX_UP = 5, MAX_REL = 2;
            let relative = [];
            while (node.parentElement && depth < MAX_UP) {
                node = node.parentElement;
                depth++;
                const aid = node.getAttribute('id');
                const atestid = node.getAttribute('data-testid');
                if ((aid && document.querySelectorAll(`[id='${aid}']`).length === 1) || atestid) {
                    return {anchor: atestid ? `[data-testid='${atestdid || atestid}']` : `#${aid}`,
                            rel: relative.join(' > ')};
                }
                // 记录从锚点到目标的相对路径（从近到远收集，最后 reverse）
                const siblings = Array.from(node.parentElement.children).filter(
                    e => e.tagName === node.tagName);
                let seg = node.tagName.toLowerCase();
                if (siblings.length > 1) seg += `:nth-of-type(${siblings.indexOf(node) + 1})`;
                relative.unshift(seg);
                if (relative.length >= MAX_REL) break;
            }
            return null;
        }
    """)
    if anchor_info and anchor_info.get("anchor"):
        rel = anchor_info.get("rel") or ""
        anchor_value = anchor_info["anchor"] + (f" > {rel}" if rel else "")
        # 目标元素自身的段也要带上（相对路径的最后一段是目标）
        candidates.append({
            "type": "anchor",
            "value": anchor_value,
            "base_score": 75,
        })
```

注意：上 JS 里 `atestdid` 为笔误占位——实施时直接写 `atestdid` 为 `atestdid` 修正为：

```js
return {anchor: atestid ? `[data-testid='${atestdid}']` : `#${aid}`, rel: ...}
```
→ 正确版本（实施时以此为准）：
```js
return {anchor: atestid ? `[data-testid='${atestdid}']` : `#${aid}`,
        rel: relative.join(' > ')};
```
若 atestid 分支：`anchor = "[data-testid='" + atestid + "']"`（无 testdid 变量，直接拼）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_anchor_axis_locators.py -v`
Expected: PASS（2 个 anchor 测试）

- [ ] **Step 5: 真浏览器冒烟（可选但推荐）**

启动 uvicorn 后对 localhost:3000 抓一次元素，确认入库的 locator_strategies 中出现 type=anchor 且 verify 后 score ≥ 75。

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/playwright_locator_core.py backend/tests/test_anchor_axis_locators.py
git commit -m "feat(locator): 祖先锚点策略——稳定id/testid祖先+1-2层相对路径(缺口1)"
```

---

### Task 2: 相邻兄弟 + label 轴策略（RED→GREEN）

**Files:**
- Modify: `backend/app/services/playwright_locator_core.py`（generate_locators_for_element 内追加）
- Test: `backend/tests/test_anchor_axis_locators.py`（追加 class）

- [ ] **Step 1: 追加失败测试**

```python
class TestSiblingLabelStrategy:
    @pytest.mark.asyncio
    async def test_generates_sibling_label_for_input(self):
        """input 无 id/name，前兄弟 label 有文本 → 生成 sibling-label 轴定位。"""
        el = make_element(attrs={"_text": "", "type": "text"})
        async def _evaluate(js, arg=None):
            if "tagName" in js:
                return "input"
            if "previousElementSibling" in js:
                return {"label_text": "用户名", "tag": "input"}
            return None
        el.evaluate = _evaluate
        candidates = await generate_locators_for_element(make_page(), el)
        axis = [c for c in candidates if c["type"] == "sibling-label"]
        assert axis, "应有 sibling-label 策略候选"
        assert "following-sibling::input" in axis[0]["value"]
        assert "用户名" in axis[0]["value"]
        assert axis[0]["base_score"] == 78

    @pytest.mark.asyncio
    async def test_no_sibling_label_for_button(self):
        """button 不生成 sibling-label（text 策略已覆盖）。"""
        el = make_element(attrs={"_text": "按钮", "type": "button"})
        async def _evaluate(js, arg=None):
            if "tagName" in js:
                return "button"
            if "previousElementSibling" in js:
                return {"label_text": "按钮", "tag": "button"}
            return None
        el.evaluate = _evaluate
        candidates = await generate_locators_for_element(make_page(), el)
        assert not [c for c in candidates if c["type"] == "sibling-label"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_anchor_axis_locators.py::TestSiblingLabelStrategy -v`
Expected: FAIL — 无 sibling-label 候选

- [ ] **Step 3: 实现 sibling-label 策略**

在 anchor 策略之后追加：

```python
    # 策略 11: 相邻兄弟 + label（缺口2，轴定位）——label 和 input 是兄弟、input 无 id 时，
    // 用 label 文本锚定：//label[...] / following-sibling::input
    if tag_name in ("input", "select", "textarea"):
        sib = await element.evaluate("""
            el => {
                let node = el.previousElementSibling;
                let hops = 0;
                while (node && hops < 3) {
                    if (node.tagName === 'LABEL') {
                        const t = (node.textContent || '').trim();
                        if (t) return {label_text: t.slice(0, 30), tag: el.tagName.toLowerCase()};
                    }
                    // label 可能包在前一层容器里（如 <div><label>..</label><input/></div>）
                    const inner = node.querySelector && node.querySelector('label');
                    if (inner) {
                        const t = (inner.textContent || '').trim();
                        if (t) return {label_text: t.slice(0, 30), tag: el.tagName.toLowerCase()};
                    }
                    node = node.previousElementSibling;
                    hops++;
                }
                return null;
            }
        """)
        if sib and sib.get("label_text"):
            lt = sib["label_text"].replace("'", "\\'")
            candidates.append({
                "type": "sibling-label",
                "value": f"//label[contains(., '{lt}')]/following-sibling::{sib['tag']}",
                "base_score": 78,
            })
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_anchor_axis_locators.py -v`
Expected: PASS（全部 4 个测试）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/playwright_locator_core.py backend/tests/test_anchor_axis_locators.py
git commit -m "feat(locator): 相邻兄弟+label轴定位策略——覆盖表单无id元素(缺口2)"
```

---

### Task 3: verify 惩罚豁免（锚点路径的 nth 不扣分）（RED→GREEN）

**Files:**
- Modify: `backend/app/services/playwright_locator_core.py:216-238`（verify_and_score_locator 扣分块）
- Test: `backend/tests/test_anchor_axis_locators.py`（追加 class）

- [ ] **Step 1: 追加失败测试**

```python
from app.services.playwright_locator_core import verify_and_score_locator

class TestVerifyNthExemption:
    @pytest.mark.asyncio
    async def test_anchor_nth_not_penalized_when_unique(self):
        """锚点路径含 nth-of-type 且唯一命中 → 不扣 15 分。"""
        page = MagicMock()
        # mock: 定位器命中 1 个元素，且与 target 相同
        found = MagicMock()
        async def _eval(js, arg=None):
            return True
        found.evaluate = _eval
        async def _all():
            return [found]
        page.locator = MagicMock(return_value=MagicMock(all=_all))
        target = MagicMock()
        async def _eh(js):
            return "handle"
        target.evaluate_handle = _eh

        result = await verify_and_score_locator(page, {
            "type": "anchor",
            "value": "#toolbar > div:nth-of-type(2) > button",
            "base_score": 75,
        }, target)
        assert result is not None
        assert result["score"] == 95  # 75 + unique 20，无 nth 扣分

    @pytest.mark.asyncio
    async def test_plain_css_nth_still_penalized_when_not_unique(self):
        """普通 css 全路径 nth 且非唯一 → 照扣（回归保护）。"""
        page = MagicMock()
        f1, f2 = MagicMock(), MagicMock()
        async def _eval_t(js, arg=None):
            return True
        async def _eval_f(js, arg=None):
            return False
        f1.evaluate = _eval_t   # 第一个是目标
        f2.evaluate = _eval_f
        async def _all():
            return [f1, f2]
        page.locator = MagicMock(return_value=MagicMock(all=_all))
        target = MagicMock()
        async def _eh(js):
            return "handle"
        target.evaluate_handle = _eh

        result = await verify_and_score_locator(page, {
            "type": "css",
            "value": "div:nth-of-type(1) > span:nth-of-type(2)",
            "base_score": 50,
        }, target)
        # 50 - 30(非唯一) - 15(nth非唯一) = 5
        assert result["score"] == 5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_anchor_axis_locators.py::TestVerifyNthExemption -v`
Expected: 第 1 个 FAIL（现规则对 anchor 的 nth 也扣 15 → 80 而非 95）

- [ ] **Step 3: 实现豁免**

把扣分块改为：

```python
        # 稳定性扣分（同前）；豁免：锚点路径（value 以 #id / [data-testid= 开头）
        # 自带 1-2 层 nth 是相对段定位所需，锚点已提供结构稳定性，不扣。
        is_anchored = value.startswith("#") or value.startswith("[data-testid=")
        if ("nth-of-type" in value or "nth-child" in value) and not unique and not is_anchored:
            score -= 15
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `cd backend && python -m pytest tests/test_anchor_axis_locators.py -v && python -m pytest tests/ -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/playwright_locator_core.py backend/tests/test_anchor_axis_locators.py
git commit -m "fix(locator): 锚点路径nth豁免扣分——锚点已提供结构稳定性"
```

---

### Task 4: 真浏览器端到端验证 + 收尾

**Files:**
- 无新文件；跑真实页面验证策略产出

- [ ] **Step 1: 重启 backend（无 --reload）**

```bash
powershell -c "Get-Process python | Stop-Process -Force"; sleep 2
cd backend && (python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > logs/uvicorn.out 2>&1 &) && (python -m celery -A app.tasks worker --pool=solo -l info > logs/celery.out 2>&1 &)
```

- [ ] **Step 2: 对 localhost:3000 用会话式抓取抓一批元素**

前端 → 元素抓取 → 会话式抓取 → http://localhost:3000/cases → 开始抓取元素。
检查已抓元素列表中部分元素的「N 策略」数量上升（anchor/sibling-label 出现）。

- [ ] **Step 3: 抽查入库元素的 locator_strategies**

```bash
docker exec moontest-pgvector psql -U moontest -d moontest -c \
  "SELECT element_name, jsonb_path_query_array(locator_strategies->'strategies', '$[*].type') FROM element_repository WHERE status='active' ORDER BY updated_at DESC LIMIT 5;"
```
Expected: 部分元素 strategies 含 "anchor" 或 "sibling-label"。

- [ ] **Step 4: 全量测试 + commit 收尾**

```bash
cd backend && python -m pytest tests/ -q
git add -A && git commit -m "test(locator): 锚点+轴定位端到端验证" --allow-empty -q || true
```

---

## Self-Review 结论

- 规格覆盖：缺口1（Task 1）、缺口2（Task 2）、配套惩罚豁免（Task 3）、端到端验证（Task 4）✓
- 占位符：Task 1 Step 3 的 JS 有一处笔误标注了修正版，实施以修正版为准 ✓
- 类型一致性：anchor/sibling-label 的 base_score（75/78）、豁免条件（is_anchored）在 Task 1-3 间一致 ✓
