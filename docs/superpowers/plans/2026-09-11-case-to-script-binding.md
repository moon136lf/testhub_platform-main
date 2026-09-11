# 用例转脚本·元素绑定方案 V1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落实 `docs/superpowers/specs/2026-09-10-case-to-script-binding-design.md`：三级匹配管线（L1/L2/L3）+ synonym 回写 + 元素绑定选择器 + 断言模板库 + 结构调整，使转换产物与用例逐行对应。

**Architecture:** 保留 step_codegen 确定性生成底子；升级 element_service.find_by_name 为评分管线并返回结构化候选；script_step 落库（新表，step_mapping JSONB 保留过渡）；StepEditor 元素格改为绑定+选择器交互；回归页并入测试集。

**Tech Stack:** FastAPI + SQLAlchemy(async) + PostgreSQL16（create_all 建表，无 alembic versions）+ Vue3 + Element Plus + pytest(770 基线)

**参考来源：** Healenium(评分公式/0.75阈值/归一化)、Midscene(LLM只选不生成)、Katalon(步骤表=事实源/同义词)、Cypress(选择器候选交互)、Robot Framework(断言词表)、TestRail/禅道(测试集引用/失败转bug)、Allure(case↔script关联)

---

## 现状要点（执行 agent 必读）

- `backend/app/services/element_service.py:36-110` `find_by_name(project_id, element_name)` 两级匹配（精确/双向ilike），返回单元素对象或 None。**测试用 FakeDB mock，改动需兼容**。
- `backend/app/services/script_pipeline.py:182-233` `step3_match_locators`，未命中走 `_ai_generate_locator`（LLM 自由生成定位器，要替换为候选单选）。`ElementLookupProto` 协议：`find(project_id, target) -> str|None`。
- `backend/app/services/step_codegen.py` SUPPORTED_ACTIONS = navigate/click/input/select/wait/assert_text/assert_visible/assert_db。
- `backend/app/models/test_case.py:135` ScriptAsset.step_mapping JSONB；`backend/app/services/script_edit_service.py:21-32` save_steps 保存+重生成。
- `backend/app/models/element.py` 无 synonym 表。
- `backend/app/api/v1/test_sets.py:18` source 校验 `^(manual|ai_suggest|convert_page)$`；`backend/app/models/test_set.py:20` 同枚举注释。
- 前端：`frontend/src/utils/scriptMapping.js`（pipeline→编辑器行映射）、`frontend/src/components/StepEditor.vue`（元素列为手填输入框）、路由 `frontend/src/router/index.js:96-98` 回归页、菜单 `frontend/src/layouts/MainLayout.vue:48`。
- 建表走 `backend/app/core/database.py:65-69` init_db 的 `Base.metadata.create_all`（新模型 import 后自动建表，PG16 localhost:5433）。
- 测试：`cd backend && venv/Scripts/python -m pytest` 基线 770 passed。celery 用 `-A app.tasks`。

---

## Task 1: 归一化 + 评分管线 find_candidates（L1/L2）

**Files:**
- Modify: `backend/app/services/element_service.py`
- Test: `backend/tests/test_element_find_candidates.py`（新建）

- [ ] **Step 1: 写失败测试——归一化函数**

```python
"""find_candidates 评分管线测试（方案V1 阶段1）。"""
from app.services.element_service import normalize_text


def test_normalize_fullwidth_punct_case():
    assert normalize_text("Ａｃｃｏｕｎｔ， 输入框！") == "account输入框"
    assert normalize_text("  获取 验证码  ") == "获取验证码"
    assert normalize_text(None) == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_find_candidates.py -v`
Expected: FAIL ImportError: cannot import name 'normalize_text'

- [ ] **Step 3: 实现 normalize_text（element_service.py 模块级函数）**

```python
def normalize_text(s: Optional[str]) -> str:
    """归一化：全角→半角、去空格/标点、lower。Healenium 预处理思路。"""
    if not s:
        return ""
    # 全角转半角
    out = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000:
            ch = " "
        elif 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        out.append(ch)
    s = "".join(out)
    # 去空白与常见标点（中英文）
    s = re.sub(r"[\s。，！？；：“”‘’\(\)（）【】《》、,.!?;:'\"()\[\]{}]+", "", s)
    return s.lower().strip()
```

- [ ] **Step 4: 跑归一化测试通过**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_find_candidates.py -v`
Expected: PASS

- [ ] **Step 5: 写失败测试——score_element 评分**

```python
from app.services.element_service import score_element


def test_score_exact_alias():
    e = {"element_name": "账号输入框", "element_text": "请输入账号", "tag": "input",
         "locators": {"strategies": [{"type": "css", "value": "#zh", "confidence": 5}]}}
    assert score_element("账号输入框", "input", e) >= 1.0


def test_score_text_containment():
    # 用例"获取验证码按钮" 包含元素text"获取验证码" → text包含满分，类型一致加分
    e = {"element_name": "获取验证码", "element_text": "获取验证码", "tag": "button",
         "locators": {"strategies": [{"type": "text", "value": "获取验证码", "confidence": 5}]}}
    s = score_element("获取验证码按钮", "click", e)
    assert 0.75 <= s < 1.0


def test_score_low_returns_below_threshold():
    e = {"element_name": "完全无关", "element_text": "", "tag": "select",
         "locators": {"strategies": []}}
    assert score_element("账号输入框", "input", e) < 0.75


def test_score_type_mismatch_penalized():
    e = {"element_name": "账号", "element_text": "", "tag": "select",
         "locators": {"strategies": []}}
    s1 = score_element("账号输入框", "input", e)  # 期望input但元素是select
    e2 = {"element_name": "账号", "element_text": "", "tag": "input",
          "locators": {"strategies": []}}
    s2 = score_element("账号输入框", "input", e2)
    assert s2 > s1
```

- [ ] **Step 6: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_find_candidates.py -v`
Expected: FAIL cannot import name 'score_element'

- [ ] **Step 7: 实现 score_element**

```python
def _token_overlap(a: str, b: str) -> float:
    """字符 bigram 重叠率（中文友好，不需要分词器）。"""
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    ga = {a[i:i+2] for i in range(len(a)-1)}
    gb = {b[i:i+2] for i in range(len(b)-1)}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def score_element(target: str, intent_action: Optional[str], elem: dict) -> float:
    """Healenium 式加权评分：别名相似 0.4 + text包含 0.3 + 类型一致 0.2 + 同名直接命中兜底 0.1。

    elem keys: element_name, element_text, tag, locators.
    intent_action: input/select/click 等（None 不计类型分）。
    """
    t = normalize_text(target)
    name = normalize_text(elem.get("element_name"))
    text = normalize_text(elem.get("element_text"))

    # L1: 归一化精确相等
    if t and (t == name or (text and t == text)):
        return 1.0

    # 别名相似度（bigram 重叠，取 name/text 较高者）
    alias_sim = max(_token_overlap(t, name), _token_overlap(t, text) if text else 0.0)

    # text 定位值包含：target 含元素名/text（"获取验证码按钮"⊃"获取验证码"）
    contain = 0.0
    for ref in (name, text):
        if ref and len(ref) >= 2 and (ref in t or t in ref):
            contain = 1.0
            break

    # 类型一致：输入类动作 → input/textarea；点击 → button/a
    type_score = 0.0
    if intent_action:
        input_tags = {"input", "textarea"}
        click_tags = {"button", "a"}
        tag = (elem.get("tag") or "").lower()
        if intent_action in ("input", "select") and tag in input_tags:
            type_score = 1.0
        elif intent_action == "click" and tag in click_tags:
            type_score = 1.0

    score = 0.4 * alias_sim + 0.3 * contain + 0.2 * type_score
    # 无任何结构化加分时的保底：仅 alias_sim 部分，已有
    return round(min(score, 0.99) if score < 1.0 else 1.0, 4)
```

注意：精确相等返回 1.0；其余封顶 0.99（保证 L1/L2 可区分）。

- [ ] **Step 8: 跑评分测试通过**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_find_candidates.py -v`
Expected: 全 PASS

- [ ] **Step 9: 写失败测试——find_candidates 管线（含阈值与排序）**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.element_service import ElementService


def _mk_elem(name="账号输入框", text="请输入账号", tag="input"):
    e = MagicMock()
    e.element_name, e.element_text, e.tag_name = name, text, tag
    e.element_id = "el-1"
    e.confidence = 5
    e.locator_strategies = {"strategies": [{"type": "css", "value": "#zh", "confidence": 5}]}
    e.page_id = "p-1"
    e.status = "active"
    return e


@pytest.mark.asyncio
async def test_find_candidates_returns_scored_list():
    svc = ElementService(db=MagicMock())
    svc.db.execute = AsyncMock(return_value=_result([_mk_elem(), _mk_elem(name="其他")]))
    cands = await svc.find_candidates("proj-1", "账号输入框", intent_action="input")
    assert cands[0]["match_level"] in ("L1", "L2")
    assert cands[0]["element_id"] == "el-1"
    assert cands[0]["score"] >= 0.75
    # 低于阈值的也被返回但标 low（供 L3 候选）
    assert any(c["score"] < 0.75 for c in cands)


@pytest.mark.asyncio
async def test_find_candidates_empty_target():
    svc = ElementService(db=MagicMock())
    assert await svc.find_candidates("proj-1", "") == []
```

- [ ] **Step 10: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_find_candidates.py -v`
Expected: FAIL no attribute 'find_candidates'

- [ ] **Step 11: 实现 find_candidates（ElementService 方法，项目全量拉回后 Python 评分）**

```python
    MATCH_THRESHOLD = 0.75
    L3_MAX_CANDIDATES = 20

    async def find_candidates(
        self, project_id: str, target: str,
        intent_action: Optional[str] = None, page_id: Optional[str] = None,
    ) -> List[Dict]:
        """三级匹配管线 L1/L2（方案V1）。返回降序列表：
        [{element_id, element_name, locator, confidence, score, match_level}]
        score>=0.75 → L1(1.0)/L2；<0.75 → level="low"（供 L3 候选，截断 L3_MAX_CANDIDATES）。
        """
        if not target:
            return []
        try:
            pid = uuid.UUID(project_id)
        except (ValueError, TypeError):
            return []
        result = await self.db.execute(
            select(ElementRepository).where(
                ElementRepository.project_id == pid,
                ElementRepository.status == "active",
            )
        )
        rows = result.scalars().all()
        if not isinstance(rows, list):
            rows = [rows] if rows is not None else []

        cands = []
        for e in rows:
            if page_id and getattr(e, "page_id", None) and str(e.page_id) != str(page_id):
                continue  # 同页面优先；全局元素（page_id 空）不过滤
            elem_dict = {
                "element_name": getattr(e, "element_name", "") or "",
                "element_text": getattr(e, "element_text", "") or "",
                "tag": getattr(e, "tag_name", "") or "",
                "locators": getattr(e, "locator_strategies", None) or {},
            }
            score = score_element(target, intent_action, elem_dict)
            level = "L1" if score >= 1.0 else ("L2" if score >= self.MATCH_THRESHOLD else "low")
            cands.append({
                "element_id": str(getattr(e, "element_id", "") or getattr(e, "id", "")),
                "element_name": elem_dict["element_name"],
                "locator": self._best_locator(elem_dict["locators"]),
                "confidence": getattr(e, "confidence", 0) or 0,
                "score": score,
                "match_level": level,
            })
        cands.sort(key=lambda c: (-c["score"], -c["confidence"]))
        # L3 候选截断
        low = [c for c in cands if c["match_level"] == "low"][: self.L3_MAX_CANDIDATES]
        high = [c for c in cands if c["match_level"] != "low"]
        return high + low

    @staticmethod
    def _best_locator(locators: dict) -> str:
        strategies = (locators or {}).get("strategies") or []
        if not strategies:
            return ""
        best = max(strategies, key=lambda s: s.get("confidence", 0) or 0)
        return best.get("value", "")
```

- [ ] **Step 12: 跑全部新测试 + 既有元素测试不回退**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_find_candidates.py tests/test_element_scanning.py -v`
Expected: 新测试 PASS，旧测试不回退

- [ ] **Step 13: Commit**

```bash
git add backend/app/services/element_service.py backend/tests/test_element_find_candidates.py
git commit -m "feat(elements): find_candidates 评分管线(归一化+bigram重叠+类型加分,0.75阈值) — 方案V1阶段1"
```

---

## Task 2: synonym 表 + 回写 + 匹配接入

**Files:**
- Modify: `backend/app/models/element.py`（加 ElementSynonym 模型）
- Modify: `backend/app/core/database.py:65-67`（import 注册）
- Modify: `backend/app/services/element_service.py`
- Test: `backend/tests/test_element_synonym.py`（新建）

- [ ] **Step 1: 写失败测试——模型与回写**

```python
"""element_synonym 表 + 人工绑定回写测试（方案V1 阶段2）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models.element import ElementSynonym
from app.services.element_service import ElementService


@pytest.mark.asyncio
async def test_write_synonym_inserts():
    svc = ElementService(db=MagicMock())
    svc.db.add = MagicMock()
    svc.db.flush = AsyncMock()
    ok = await svc.write_synonym("el-1", "账号输入框", source="manual_binding")
    assert ok
    svc.db.add.assert_called_once()
    syn = svc.db.add.call_args[0][0]
    assert isinstance(syn, ElementSynonym)
    assert syn.synonym_text == "账号输入框"
    assert syn.source == "manual_binding"


@pytest.mark.asyncio
async def test_write_synonym_dedup():
    """同 element+text 已存在 → 不重复插入。"""
    svc = ElementService(db=MagicMock())
    existing = MagicMock(spec=ElementSynonym)
    svc.db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing)))
    ok = await svc.write_synonym("el-1", "账号输入框")
    assert ok
    svc.db.add.assert_not_called()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_synonym.py -v`
Expected: FAIL ImportError: cannot import name 'ElementSynonym'

- [ ] **Step 3: 实现 ElementSynonym 模型（element.py 末尾追加）**

```python
class ElementSynonym(Base):
    """元素同义词（方案V1）：用例目标词→元素 的人工绑定/自动回写。"""
    __tablename__ = "element_synonyms"
    __table_args__ = (
        UniqueConstraint("element_id", "synonym_text", name="uq_synonym_element_text"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    element_id = Column(UUID(as_uuid=True), ForeignKey("element_repository.id", ondelete="CASCADE"), nullable=False, index=True)
    synonym_text = Column(String(200), nullable=False, comment="用例目标词原文")
    source = Column(String(20), nullable=False, default="manual_binding", comment="manual_binding/ai_l2_hit")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

并在 `backend/app/core/database.py` 的 init_db import 处（65-67 行附近）加 `from app.models import element` 已有——确认 `app/models/__init__.py` 导出或直接被 element.py 模块注册即可（同文件内新增类自动注册到 Base.metadata，无需改 database.py；**核对 `backend/app/models/__init__.py` 若做显式 re-export 则补 ElementSynonym**）。

- [ ] **Step 4: 跑模型测试通过**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_synonym.py -v`
Expected: PASS

- [ ] **Step 5: 写失败测试——write_synonym 服务方法（上面测试已含）+ find_candidates 接入 synonym**

```python
@pytest.mark.asyncio
async def test_find_candidates_synonym_hit_high_score():
    """synonym 表命中（归一化相等）→ score=0.9, level=L2。"""
    svc = ElementService(db=MagicMock())
    syn = MagicMock()
    syn.element_id = "el-1"
    syn.synonym_text = "账号输入框"
    # 第一次 execute 返回 synonym 行，第二次返回元素全量
    elem = _mk_elem(name="输入框1")  # 别名与目标差很远，仅靠 synonym 命中
    results = [
        MagicMock(scalars=MagicMock(all=MagicMock(return_value=[syn]))),
        MagicMock(scalars=MagicMock(all=MagicMock(return_value=[elem]))),
    ]
    svc.db.execute = AsyncMock(side_effect=results)
    cands = await svc.find_candidates("proj-1", "账号输入框", intent_action="input")
    top = cands[0]
    assert top["element_id"] == "el-1"
    assert top["match_level"] == "L2"
    assert 0.85 <= top["score"] <= 0.95
```

- [ ] **Step 6: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_synonym.py -v`
Expected: FAIL（synonym 查询未接入，score 来自普通评分大概率 <0.75 或 level 错）

- [ ] **Step 7: find_candidates 接入 synonym（在拉全量元素前先查 synonym）**

在 `find_candidates` 中，`result = await self.db.execute(select(ElementRepository)...)` 之前插入：

```python
        # synonym 命中优先（Katalon 同义词机制）：归一化相等的 synonym → score=0.9
        syn_result = await self.db.execute(
            select(ElementSynonym).where(ElementSynonym.synonym_text == target)
        )
        try:
            syn_rows = syn_result.scalars().all()
        except Exception:
            syn_rows = []
        syn_scores = {}
        if isinstance(syn_rows, list):
            for s in syn_rows:
                if normalize_text(getattr(s, "synonym_text", "")) == normalize_text(target):
                    eid = str(getattr(s, "element_id", ""))
                    if eid:
                        syn_scores[eid] = 0.9
```

评分循环中合并：命中 synonym 的元素 score 取 `max(普通评分, 0.9)`，level 相应改 "L2"（0.9）或保持 L1（若普通评分=1.0）。

- [ ] **Step 8: 跑全部通过 + 旧测试不回退**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_element_synonym.py tests/test_element_find_candidates.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/element.py backend/app/services/element_service.py backend/tests/test_element_synonym.py backend/app/models/__init__.py
git commit -m "feat(elements): element_synonyms 表+回写钩子+find_candidates synonym优先命中 — 方案V1阶段2"
```

---

## Task 3: pipeline 接入评分管线 + L3 候选单选

**Files:**
- Modify: `backend/app/services/script_pipeline.py`（step3 + ElementLookupProto + _ai_pick_element）
- Test: `backend/tests/test_pipeline_l3_pick.py`（新建）

- [ ] **Step 1: 写失败测试——ElementCandidate 协议与 step3 带回 element 信息**

```python
"""step3 接入评分管线 + L3 AI 候选单选测试（方案V1 阶段2/3）。"""
import pytest
from app.services.script_pipeline import step3_match_locators, ActionIntent, ActionWithLocator


class FakeCandidates:
    """find_candidates 协议实现：返回结构化候选。"""
    def __init__(self, by_target):
        self.by_target = by_target

    async def find_candidates(self, project_id, target, intent_action=None, page_id=None):
        return self.by_target.get((target, intent_action), [])


class FakeGateway:
    def __init__(self, pick=0):
        self.pick = pick
        self.calls = []

    async def chat(self, messages):
        self.calls.append(messages)
        return {"content": f'{{"pick": {self.pick}}}'}


def _act(step, action, target, value=None):
    return ActionIntent(step=step, action=action, target=target, value=value)


@pytest.mark.asyncio
async def test_step3_l2_hit_binds_element():
    cands = {("账号输入框", "input"): [
        {"element_id": "el-1", "element_name": "请输入账号", "locator": "#zh",
         "confidence": 5, "score": 0.82, "match_level": "L2"}]}
    results = await step3_match_locators(
        [_act(1, "fill", "账号输入框", "test02")], "p1",
        lookup=FakeCandidates(cands), ai_optimize=False, gateway=None)
    r = results[0]
    assert r.locator == "#zh"
    assert r.locator_status == "matched"
    assert r.element_id == "el-1"
    assert r.element_name == "请输入账号"
    assert r.match_score == 0.82


@pytest.mark.asyncio
async def test_step3_miss_stays_draft_no_ai():
    results = await step3_match_locators(
        [_act(1, "fill", "不存在的东西", "x")], "p1",
        lookup=FakeCandidates({}), ai_optimize=False, gateway=None)
    r = results[0]
    assert r.locator_status == "none_draft"
    assert r.locator is None


@pytest.mark.asyncio
async def test_step3_l3_ai_pick_from_candidates():
    """L3：未命中+ai_optimize → 候选清单给 LLM 单选，不生成定位器。"""
    cands = {("神秘控件", "click"): [
        {"element_id": "el-a", "element_name": "按钮A", "locator": "#a", "confidence": 3, "score": 0.3, "match_level": "low"},
        {"element_id": "el-b", "element_name": "按钮B", "locator": "#b", "confidence": 3, "score": 0.2, "match_level": "low"},
    ]}
    gw = FakeGateway(pick=1)
    results = await step3_match_locators(
        [_act(1, "click", "神秘控件")], "p1",
        lookup=FakeCandidates(cands), ai_optimize=True, gateway=gw)
    r = results[0]
    assert r.locator == "#b"
    assert r.locator_status == "pending_confirm"
    assert r.element_id == "el-b"
    # prompt 里只含候选清单，不含"生成定位器"
    prompt_text = str(gw.calls[0])
    assert "按钮B" in prompt_text


@pytest.mark.asyncio
async def test_step3_l3_invalid_pick_falls_to_draft():
    cands = {("神秘控件", "click"): [
        {"element_id": "el-a", "element_name": "按钮A", "locator": "#a", "confidence": 3, "score": 0.3, "match_level": "low"}]}
    gw = FakeGateway(pick=99)  # 越界
    results = await step3_match_locators(
        [_act(1, "click", "神秘控件")], "p1",
        lookup=FakeCandidates(cands), ai_optimize=True, gateway=gw)
    assert results[0].locator_status == "none_draft"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_pipeline_l3_pick.py -v`
Expected: FAIL TypeError（ActionWithLocator 无 element_id/match_score 参数）

- [ ] **Step 3: 实现——替换 step3_match_locators**

script_pipeline.py 修改（保留 locator_source 聚合语义）：

```python
@dataclass
class ActionWithLocator:
    step: int
    action: str
    target: Optional[str]
    value: Optional[str]
    locator: Optional[str] = None
    locator_status: str = "none_draft"
    locator_source: str = "none_draft"
    element_id: Optional[str] = None
    element_name: Optional[str] = None
    match_score: Optional[float] = None


class CandidatesLookupProto(Protocol):
    """评分管线协议: find_candidates(project_id, target, intent_action, page_id) -> List[Dict]。"""
    async def find_candidates(self, project_id: str, target: str,
                              intent_action: Optional[str] = None,
                              page_id: Optional[str] = None) -> List[Dict]: ...


STEP3_PICK_PROMPT = """你是元素选择器。从候选元素中为用例步骤目标选出最匹配的一个，只输出 JSON。
目标: {target}
候选(编号|别名|定位|类型):
{candidates}
输出格式: {{"pick": 编号}}，都不合适则 {{"pick": null}}。"""


async def _ai_pick_element(target: str, candidates: List[Dict], gateway) -> Optional[Dict]:
    """Midscene 模式：LLM 只从候选中选，不生成定位器。"""
    lines = "\n".join(
        f"{i}|{c.get('element_name','')}|{c.get('locator','')}|{c.get('match_level','')}"
        for i, c in enumerate(candidates))
    resp = await gateway.chat([{"role": "user", "content": STEP3_PICK_PROMPT.format(target=target, candidates=lines)}])
    import json as _json
    try:
        m = re.search(r"\{[^}]*\}", resp["content"])
        pick = _json.loads(m.group(0)).get("pick") if m else None
        if isinstance(pick, int) and 0 <= pick < len(candidates):
            return candidates[pick]
    except (ValueError, AttributeError):
        pass
    return None


async def step3_match_locators(
    actions: List[ActionIntent],
    project_id: str,
    lookup: CandidatesLookupProto,
    ai_optimize: bool,
    gateway: Optional[LLMGatewayProto],
) -> List[ActionWithLocator]:
    """Step3 方案V1：L1/L2 评分命中→绑定；未命中→L3 候选单选（可关）→draft。"""
    results: List[ActionWithLocator] = []
    matched = 0
    ai_used = False
    for a in actions:
        cands = await lookup.find_candidates(project_id, a.target, intent_action=a.action) if a.target else []
        top = cands[0] if cands and cands[0].get("match_level") in ("L1", "L2") else None
        if top:
            status, loc = "matched", top["locator"]
            matched += 1
        elif ai_optimize and gateway is not None and cands:
            picked = await _ai_pick_element(a.target, cands, gateway)
            if picked:
                status, loc = "pending_confirm", picked["locator"]
                matched += 1
                ai_used = True
            else:
                status, loc = "none_draft", None
        else:
            status, loc = "none_draft", None
        results.append(ActionWithLocator(
            step=a.step, action=a.action, target=a.target, value=a.value,
            locator=loc, locator_status=status,
            element_id=(top or (picked if status == "pending_confirm" else None) or {}).get("element_id"),
            element_name=(top or (picked if status == "pending_confirm" else None) or {}).get("element_name"),
            match_score=(top or (picked if status == "pending_confirm" else None) or {}).get("score"),
        ))
    # locator_source 聚合逻辑保持原样（element_library/ai_generated/mixed/none_draft）
    total = len(results)
    if matched == 0:
        source = "none_draft"
    elif ai_used and matched < total:
        source = "mixed"
    elif ai_used:
        source = "ai_generated"
    elif matched < total:
        source = "mixed"
    else:
        source = "element_library"
    for r in results:
        r.locator_source = source
    return results
```

**注意**：`picked` 变量作用域——每轮循环开头 `picked = None`。上面为示意，实现时把 `(top or (picked if ...))` 整理为先算 `bound = top or picked` 再取字段，避免引用未定义。同时**同步修改 ElementService 使其满足新协议**（把 find_by_name 适配为 find_candidates 已在 Task 1 完成；此处检查 scripts.py 里 lookup 注入点——`backend/app/api/v1/scripts.py` 中构造 lookup 的地方改为传 ElementService 实例本身，因其已有 find_candidates）。

- [ ] **Step 4: 跑新测试通过**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_pipeline_l3_pick.py -v`
Expected: PASS

- [ ] **Step 5: 修复受影响的既有 pipeline/convert 测试（FakeLookup 的 find 方法改 find_candidates 签名）**

Run: `cd backend && venv/Scripts/python -m pytest tests/ -k "pipeline or convert or script" -v`
Expected: 列出需要改 mock 的测试；逐个把 FakeLookup 的 `async def find(self, project_id, target)` 改为 `async def find_candidates(self, project_id, target, intent_action=None, page_id=None)`，返回值从字符串改为 `[{"element_id":..., "element_name":..., "locator": <原字符串>, "confidence": 5, "score": 1.0, "match_level": "L1"}]`

- [ ] **Step 6: 全量回归**

Run: `cd backend && venv/Scripts/python -m pytest`
Expected: 770+ 全 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/script_pipeline.py backend/tests/test_pipeline_l3_pick.py backend/tests/  # 只 stage 实际改动的测试文件
git commit -m "feat(pipeline): step3接入评分管线+L3候选单选(替代LLM自由生成定位器) — 方案V1阶段3"
```

---

## Task 4: script_step 表 + steps 端点 + 绑定回写 synonym

**Files:**
- Create: `backend/app/models/script_step.py`
- Modify: `backend/app/models/__init__.py`（re-export）
- Modify: `backend/app/api/v1/scripts.py`
- Modify: `backend/app/services/script_edit_service.py`
- Test: `backend/tests/test_script_step_table.py`（新建）

- [ ] **Step 1: 写失败测试——模型与服务**

```python
"""script_step 表 + steps 端点测试（方案V1 阶段3）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models.script_step import ScriptStep
from app.services.script_edit_service import ScriptEditService


@pytest.mark.asyncio
async def test_save_steps_persists_script_step_rows():
    svc = ScriptEditService(db=MagicMock())
    asset = MagicMock()
    asset.id = "sc-1"
    svc.db.get = AsyncMock(return_value=asset)
    svc.db.add_all = MagicMock()
    svc.db.query = MagicMock()
    svc.db.query.return_value.filter.return_value.delete = MagicMock(return_value=1)
    svc.db.commit = AsyncMock()
    steps = [{
        "seq": 1, "action": "input", "target": "#zh", "value": "test02",
        "element_name": "请输入账号", "expected": "显示test02",
        "element_id": "el-1", "case_step_no": 2,
    }]
    saved = await svc.save_steps("sc-1", "登录脚本", steps)
    # 行落 script_step 表（除写 step_mapping JSONB 外新增）
    rows = [c for c in svc.db.add_all.call_args[0][0]]
    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r, ScriptStep)
    assert r.element_id == "el-1"
    assert r.case_step_no == 2
    assert r.assertion == "显示test02"


@pytest.mark.asyncio
async def test_manual_binding_writes_synonym():
    """人工绑定（steps 带 element_id 且 element_name 是用户改过的）→ 回写 synonym。"""
    svc = ScriptEditService(db=MagicMock())
    asset = MagicMock(); asset.id = "sc-1"
    svc.db.get = AsyncMock(return_value=asset)
    svc.db.add_all = MagicMock()
    svc.db.query = MagicMock()
    svc.db.query.return_value.filter.return_value.delete = MagicMock(return_value=1)
    svc.db.commit = AsyncMock()
    svc.write_synonym = AsyncMock(return_value=True)
    steps = [{"seq": 1, "action": "click", "target": "#login", "value": "",
              "element_name": "登录按钮", "expected": "",
              "element_id": "el-9", "case_step_no": 5, "case_target_text": "确定登录的按钮"}]
    await svc.save_steps("sc-1", "t", steps)
    svc.write_synonym.assert_awaited_once_with("el-9", "确定登录的按钮", source="manual_binding")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_script_step_table.py -v`
Expected: FAIL ImportError cannot import name 'ScriptStep'

- [ ] **Step 3: 实现 ScriptStep 模型（新建 backend/app/models/script_step.py）**

```python
"""ScriptStep 模型（方案V1）：可视化步骤表=脚本本体，行落库支持用例溯源。"""
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class ScriptStep(Base):
    __tablename__ = "script_steps"
    __table_args__ = (
        UniqueConstraint("script_id", "step_no", name="uq_script_step_no"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    script_id = Column(UUID(as_uuid=True), ForeignKey("script_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    step_no = Column(Integer, nullable=False, comment="步骤序号(1起)")
    case_step_no = Column(Integer, comment="溯源：用例步骤号，可空")
    action = Column(String(30), nullable=False)
    element_id = Column(UUID(as_uuid=True), ForeignKey("element_repository.id", ondelete="SET NULL"), nullable=True)
    extra_element_id = Column(UUID(as_uuid=True), ForeignKey("element_repository.id", ondelete="SET NULL"), nullable=True, comment="辅元素(识别验证码:源图)")
    target = Column(String(500), default="", comment="定位符快照(元素改版不影响已生成脚本)")
    value = Column(Text, default="")
    assertion = Column(Text, default="", comment="期望值")
    assertion_type = Column(String(30), default="", comment="expect_text/expect_url/expect_value/expect_attribute/expect_toast")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

在 `backend/app/models/__init__.py` 补 re-export（照 ScriptAsset 现有格式），并确认 `script_assets` 表名——**执行时先 `grep -n "__tablename__" backend/app/models/test_case.py` 核对 ScriptAsset 实际表名，FK 指向它**。

- [ ] **Step 4: 跑模型测试通过**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_script_step_table.py -v`
Expected: PASS（模型部分）

- [ ] **Step 5: 实现 save_steps 扩展（script_edit_service.py）**

```python
from app.models.script_step import ScriptStep
from app.models.element import ElementSynonym  # 若 write_synonym 在 element_service


class ScriptEditService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._element_service = None

    @property
    def element_service(self):
        if self._element_service is None:
            from app.services.element_service import ElementService
            self._element_service = ElementService(self.db)
        return self._element_service

    async def save_steps(self, script_id: str, title: str, steps: List[Dict]) -> ScriptAsset:
        """保存步骤化编辑。步骤行同步落 script_steps 表；人工绑定回写 synonym。"""
        asset = await self.db.get(ScriptAsset, UUID(script_id))
        if not asset:
            raise ValueError("脚本不存在")
        if not steps:
            raise ValueError("至少需要一个步骤")
        asset.content = generate_script(title or asset.name, steps)
        asset.step_mapping = steps
        asset.version = (asset.version or 1) + 1

        # script_step 行：先清后插（脚本内步骤全量替换）
        await self.db.execute(
            sa_delete(ScriptStep).where(ScriptStep.script_id == asset.id)
        )
        from app.models.element import ElementRepository
        for i, s in enumerate(steps, start=1):
            element_uuid = None
            if s.get("element_id"):
                try:
                    element_uuid = UUID(str(s["element_id"]))
                except ValueError:
                    element_uuid = None
            self.db.add(ScriptStep(
                script_id=asset.id, step_no=i,
                case_step_no=s.get("case_step_no"),
                action=s.get("action", ""),
                element_id=element_uuid,
                extra_element_id=_to_uuid(s.get("extra_element_id")),
                target=s.get("target", ""),
                value=s.get("value", ""),
                assertion=s.get("expected", ""),
                assertion_type=s.get("assertion_type", ""),
            ))
            # 人工绑定回写 synonym（有 element_id 且带用例目标词原文）
            if element_uuid and s.get("case_target_text"):
                try:
                    await self.element_service.write_synonym(
                        str(element_uuid), s["case_target_text"], source="manual_binding")
                except Exception:
                    logger.warning("synonym 回写失败，不阻断保存", exc_info=True)
        await self.db.commit()
        return asset


def _to_uuid(v):
    if not v:
        return None
    try:
        return UUID(str(v))
    except ValueError:
        return None
```

（需 `from sqlalchemy import delete as sa_delete`；`write_synonym` 签名对齐 Task 2——若 Task 2 用 element_uuid 直接收字符串也兼容。）

- [ ] **Step 6: 跑服务测试通过**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_script_step_table.py -v`
Expected: PASS

- [ ] **Step 7: steps API 端点（scripts.py 已有 PUT /{script_id}/content 接收行式步骤——扩展该端点透传新字段即可，前端 rows 加 element_id/case_step_no/case_target_text 字段自动带过）**

核对 `backend/app/api/v1/scripts.py:292-304`：现 schema 若过滤未知字段则放宽（步骤行是 Dict 透传）。测试：

```python
@pytest.mark.asyncio
async def test_content_endpoint_passthrough_new_fields(client, monkeypatch):
    """PUT /scripts/{id}/content 对 element_id/case_step_no/case_target_text 透传。"""
    captured = {}

    async def fake_save(self, script_id, title, steps):
        captured["steps"] = steps
        asset = MagicMock(); asset.id = script_id; asset.version = 2
        return asset

    monkeypatch.setattr(ScriptEditService, "save_steps", fake_save)
    resp = await client.put("/api/v1/scripts/sc-1/content", json={
        "title": "t",
        "steps": [{"seq": 1, "action": "input", "target": "#zh", "value": "v",
                   "element_name": "e", "expected": "",
                   "element_id": "el-1", "case_step_no": 3, "case_target_text": "账号输入框"}],
    })
    assert resp.status_code == 200
    assert captured["steps"][0]["element_id"] == "el-1"
    assert captured["steps"][0]["case_step_no"] == 3
```

（client fixture 照既有 scripts API 测试的写法，先看 `backend/tests/test_script_*.py` 现有 conftest。）

- [ ] **Step 8: 全量回归 + Commit**

Run: `cd backend && venv/Scripts/python -m pytest`
Expected: 全 PASS

```bash
git add backend/app/models/script_step.py backend/app/models/__init__.py backend/app/services/script_edit_service.py backend/app/api/v1/scripts.py backend/tests/test_script_step_table.py
git commit -m "feat(scripts): script_steps表+保存落库+人工绑定回写synonym+content透传绑定字段 — 方案V1阶段4"
```

---

## Task 5: codegen 扩词表（input_captcha 辅元素 / assert_url / assert_attribute）

**Files:**
- Modify: `backend/app/services/step_codegen.py`
- Test: `backend/tests/test_step_codegen_v2.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""codegen 扩词表测试（方案V1 阶段4）：input_captcha/assert_url/assert_attribute。"""
import pytest
from app.services.step_codegen import generate_script, SUPPORTED_ACTIONS


def test_input_captcha_uses_extra_element():
    SUPPORTED_ACTIONS.append("input_captcha")
    code = generate_script("t", [
        {"seq": 1, "action": "input_captcha", "target": "#captcha-input",
         "value": "", "element_name": "验证码输入框",
         "extra_target": "#captcha-img", "expected": ""},
    ])
    assert "recognize" in code or "captcha" in code
    assert "#captcha-input" in code and "#captcha-img" in code
    SUPPORTED_ACTIONS.remove("input_captcha")


def test_assert_url_contains():
    code = generate_script("t", [
        {"seq": 1, "action": "assert_url", "target": "", "value": "", "expected": "/login"},
    ])
    assert "page.url" in code and "/login" in code


def test_assert_attribute_password():
    code = generate_script("t", [
        {"seq": 2, "action": "assert_attribute", "target": "#pwd", "value": "type",
         "expected": "password"},
    ])
    assert 'get_attribute("type")' in code and "password" in code


def test_unknown_action_still_raises():
    with pytest.raises(ValueError):
        generate_script("t", [{"seq": 1, "action": "no_such", "target": "", "value": ""}])
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_step_codegen_v2.py -v`
Expected: FAIL（input_captcha 报未知操作 / assert_url/assert_attribute 不存在）

- [ ] **Step 3: 实现（step_codegen.py）**

```python
SUPPORTED_ACTIONS = [
    "navigate", "click", "input", "select", "wait",
    "assert_text", "assert_visible", "assert_db",
    "input_captcha", "assert_url", "assert_attribute",  # 方案V1
]
```

`_gen_step` 增加（在现有 assert_db 分支附近，参照其风格）：

```python
    if action == "input_captcha":
        # 辅元素复合操作：target=验证码输入框, extra_target=验证码图片
        if not target:
            raise ValueError("input_captcha 需要 target（验证码输入框定位）")
        extra = step.get("extra_target", "")
        if not extra:
            raise ValueError("input_captcha 需要 extra_target（验证码图片定位）")
        line = (
            f"    _captcha_img = {_loc(extra)}\n"
            f"    captcha_text = _recognize_captcha(_captcha_img.screenshot())  # 由执行器注入\n"
            f"    {_loc(target)}.fill(captcha_text)"
        )
        return line
    if action == "assert_url":
        if not inline_expected:
            raise ValueError("assert_url 需要 expected（URL 包含串）")
        return (
            f'    assert {_escape(inline_expected)} in page.url, '
            f'"URL 不含 " + {_escape(inline_expected)}'
        )
    if action == "assert_attribute":
        if not target or not value:
            raise ValueError("assert_attribute 需要 target 与 value(属性名)")
        return (
            f'    assert {_loc(target)}.get_attribute({_escape(value)}) == {_escape(inline_expected)}, '
            f'"属性 " + {_escape(value)} + " 不符"'
        )
```

注意：`_recognize_captcha` 与 assert_db 同策略——执行器注入，codegen 只生成调用。若现有 assert_db 的注入机制是别的形式（先读 `step_codegen.py` 的 assert_db 分支与 `_FOOTER`），**照现有 assert_db 的生成样式对齐**。

- [ ] **Step 4: 跑通过 + 旧 codegen 测试不回退**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_step_codegen_v2.py tests/ -k codegen -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/step_codegen.py backend/tests/test_step_codegen_v2.py
git commit -m "feat(codegen): 扩词表 input_captcha(辅元素)/assert_url/assert_attribute — 方案V1阶段5"
```

---

## Task 6: 断言推断确定性模板库前置

**Files:**
- Modify: `backend/app/services/script_pipeline.py`（step2 前置规则引擎）
- Test: `backend/tests/test_assertion_template.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""断言推断确定性模板库测试（方案V1 阶段6，Robot Framework 词表思路）。"""
from app.services.script_pipeline import infer_assertion_rule


def test_expect_value_from_display():
    # "显示test02" + 测试数据 test02 → expect_value
    a = infer_assertion_rule("输入", "账号输入框", "test02", "显示test02", "input")
    assert a is not None and a["assertion_type"] == "expect_value"
    assert a["expected"] == "test02"


def test_expect_url_from_navigate():
    a = infer_assertion_rule("输入", "浏览器地址栏", "http://x/login", "进入登录页", "navigate")
    assert a["assertion_type"] == "expect_url"
    assert a["expected"] == "login"  # 从数据 URL 提取 path 尾段


def test_expect_attribute_password():
    a = infer_assertion_rule("输入", "密码输入框", "123456", "显示为密文", "input")
    assert a["assertion_type"] == "expect_attribute"
    assert a["expected"] == "password"


def test_expect_toast_from_success_word():
    a = infer_assertion_rule("点击", "登录按钮", "", "欢迎登陆，提示成功", "click")
    assert a["assertion_type"] in ("expect_toast", "expect_text")


def test_uninferable_returns_none():
    assert infer_assertion_rule("点击", "某按钮", "", "触发某种效果", "click") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_assertion_template.py -v`
Expected: FAIL ImportError

- [ ] **Step 3: 实现规则函数（script_pipeline.py 模块级）**

```python
ASSERTION_RULES_DOC = """预期结果→断言类型模板库（方案V1）：
- 显示/输入了X 且测试数据=X → expect_value
- 进入/跳转/URL → expect_url（从 value URL 提取 path）
- 密文/密码 → expect_attribute(type==password)
- 成功/欢迎/提示 + 点击 → expect_toast
- 其他含引号或"包含"的明确文案 → expect_text
推断不出 → None（走 LLM 兜底）"""


def infer_assertion_rule(op: str, target: str, value: str, expected_text: str, action: str):
    """确定性断言推断。返回 {assertion_type, expected, target} 或 None。"""
    if not expected_text:
        return None
    t = expected_text

    if "密文" in t or ("密码" in t and "显示" in t):
        return {"assertion_type": "expect_attribute", "expected": "password", "target": target}

    if action == "navigate" or any(k in t for k in ("进入", "跳转", "URL", "地址")):
        # 从测试数据 URL 提取 path 尾段作期望
        path = ""
        if value and value.startswith("http"):
            path = value.rstrip("/").rsplit("/", 1)[-1] or value
        exp = path or t
        return {"assertion_type": "expect_url", "expected": exp, "target": ""}

    if value and value in t and ("显示" in t or "输入" in t):
        return {"assertion_type": "expect_value", "expected": value, "target": target}

    if action == "click" and any(k in t for k in ("成功", "欢迎", "提示")):
        return {"assertion_type": "expect_toast", "expected": t, "target": ""}

    if "包含" in t or "显示" in t:
        # 提取引号内文案，否则整句
        import re as _re
        m = _re.search(r"[“\"'](.+?)[”\"']", t)
        return {"assertion_type": "expect_text", "expected": m.group(1) if m else t, "target": target}

    return None
```

- [ ] **Step 4: 接入 step2（规则优先，LLM 兜底）**

在 `script_pipeline.py` 的 step2 处（读 101-163 行现有实现后），于 LLM 调用**之前**插入规则推断，命中且 is_valid 的直接采用（不再对同一行调 LLM）；未命中的行保持现有 LLM 推断。保持 AssertionPlan 输出结构不变，新增字段 `assertion_type` 直接映射（ambiguous → is_valid=False 不变）。

- [ ] **Step 5: 跑通过 + 既有 pipeline 测试不回退**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_assertion_template.py tests/ -k "pipeline or convert" -v`
Expected: PASS（既有 LLM 兜底测试可能需要 mock 调整：规则先命中的行 LLM 不再被调——断言 mock 的调用次数按实际调整）

- [ ] **Step 6: 全量回归 + Commit**

Run: `cd backend && venv/Scripts/python -m pytest`
Expected: 全 PASS

```bash
git add backend/app/services/script_pipeline.py backend/tests/test_assertion_template.py
git commit -m "feat(pipeline): 断言推断确定性模板库前置(expect_value/url/attribute/toast),LLM兜底 — 方案V1阶段6"
```

---

## Task 7: 转换 SSE 逐步骤直播 + 汇总

**Files:**
- Modify: `backend/app/services/script_convert_service.py`（step3 循环逐条 sse.send）
- Test: `backend/tests/test_convert_sse_steps.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""转换 SSE 逐步骤绑定明细测试（方案V1 阶段7）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.script_convert_service import ScriptConvertService


@pytest.mark.asyncio
async def test_sse_emits_per_step_binding_detail():
    sent = []

    class FakeSSE:
        async def send(self, event):
            sent.append(event)

    svc = ScriptConvertService(db=MagicMock(), sse=FakeSSE())
    svc._emit_step_binding = AsyncMock(wraps=None)  # 先确认方法存在
    # 直接测 emit 消息格式
    await svc._emit_step_binding(FakeSSE(), 2, "账号输入框", "L2", "请输入账号", "#zh", 0.82, matched=True)
    assert any("步骤2" in str(e) and "L2" in str(e) and "0.82" in str(e) for e in sent)


@pytest.mark.asyncio
async def test_sse_summary_event():
    sent = []

    class FakeSSE:
        async def send(self, event):
            sent.append(event)

    svc = ScriptConvertService(db=MagicMock())
    await svc._emit_summary(FakeSSE(), total=7, bound=6, pending=1)
    assert any("6/7" in str(e) for e in sent)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_convert_sse_steps.py -v`
Expected: FAIL AttributeError: _emit_step_binding

- [ ] **Step 3: 实现（script_convert_service.py）**

```python
    async def _emit_step_binding(self, sse, step_no, target, level, element_name, locator, score, matched):
        if matched:
            msg = f"步骤{step_no} 目标[{target}] → {level}命中[{element_name} {locator} score={score}] ✅"
        else:
            msg = f"步骤{step_no} 目标[{target}] → 未命中，留空待选择 ⚠️"
        await sse.send({"event": "step_binding", "data": {"step": step_no, "message": msg, "matched": matched}})

    async def _emit_summary(self, sse, total, bound, pending):
        await sse.send({"event": "summary", "data": {
            "message": f"绑定 {bound}/{total}、待选择 {pending}", "total": total, "bound": bound, "pending": pending}})
```

并在现有转换流程（读 `script_convert_service.py:31-90` 现状）的步骤循环处逐条调用 `_emit_step_binding`（数据来自 Task 3 的 ActionWithLocator.element_name/match_score/match_level），循环结束后调 `_emit_summary`。SSE 事件名与前端事件监听对齐（前端 ScriptConvert.vue 现有 sse 监听加 `step_binding`/`summary` 两个 case，消息直接 append 到直播区）。

- [ ] **Step 4: 跑通过**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_convert_sse_steps.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_convert_service.py backend/tests/test_convert_sse_steps.py
git commit -m "feat(convert): SSE逐步骤绑定明细直播+绑定汇总事件 — 方案V1阶段7"
```

---

## Task 8: GET /elements/picker 端点

**Files:**
- Modify: `backend/app/api/v1/elements.py`
- Test: `backend/tests/test_elements_picker.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""元素选择器数据源端点测试（方案V1，Cypress 选择器交互）。"""
import pytest


@pytest.mark.asyncio
async def test_picker_returns_grouped_elements(client, monkeypatch):
    async def fake_list(self, project_id, page_id=None, q=None):
        return {"pages": [{"page_id": "p1", "page_name": "登录页",
                           "elements": [{"element_id": "el-1", "element_name": "请输入账号",
                                         "locator": "#zh", "confidence": 5}]}]}

    from app.services.element_service import ElementService
    monkeypatch.setattr(ElementService, "picker_data", fake_list)
    resp = await client.get("/api/v1/elements/picker", params={"project_id": "p1", "q": "账号"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pages"][0]["elements"][0]["element_name"] == "请输入账号"


@pytest.mark.asyncio
async def test_picker_requires_project(client):
    resp = await client.get("/api/v1/elements/picker")
    assert resp.status_code == 422
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_elements_picker.py -v`
Expected: FAIL 404（无此路由）

- [ ] **Step 3: 实现（elements.py + element_service.picker_data）**

element_service.py 加：

```python
    async def picker_data(self, project_id: str, page_id: Optional[str] = None, q: Optional[str] = None) -> Dict:
        """元素选择器数据源：按页面分组，alias+首选定位+confidence。"""
        stmt = (
            select(PageRepository, ElementRepository)
            .join(ElementRepository, ElementRepository.page_id == PageRepository.id)
            .where(PageRepository.project_id == uuid.UUID(project_id))
        )
        if page_id:
            stmt = stmt.where(PageRepository.id == uuid.UUID(page_id))
        if q:
            kw = f"%{q}%"
            stmt = stmt.where(or_(ElementRepository.element_name.ilike(kw), ElementRepository.element_text.ilike(kw)))
        result = await self.db.execute(stmt)
        rows = result.all()
        pages: Dict[str, dict] = {}
        for page, el in rows:
            pg = pages.setdefault(str(page.id), {
                "page_id": str(page.id), "page_name": page.page_name, "elements": []})
            strategies = (el.locator_strategies or {}).get("strategies") or []
            best = max(strategies, key=lambda s: s.get("confidence", 0) or 0) if strategies else {}
            pg["elements"].append({
                "element_id": str(el.id),
                "element_name": el.element_name,
                "locator": best.get("value", ""),
                "confidence": el.confidence or 0,
            })
        return {"pages": list(pages.values())}
```

elements.py 加端点：

```python
@router.get("/picker")
async def element_picker(
    project_id: str = Query(...), page_id: Optional[str] = Query(None), q: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    svc = ElementService(db)
    return await svc.picker_data(project_id, page_id, q)
```

（import 与既有端点对齐；client fixture 照 `backend/tests/test_element_*.py` 现有写法。）

- [ ] **Step 4: 跑通过 + 全量回归**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_elements_picker.py && venv/Scripts/python -m pytest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/elements.py backend/app/services/element_service.py backend/tests/test_elements_picker.py
git commit -m "feat(elements): GET /elements/picker 选择器数据源(按页面分组+搜索) — 方案V1阶段8"
```

---

## Task 9: 前端——StepEditor 元素绑定选择器 + 待选择标记 + scriptMapping 带绑定字段

**Files:**
- Modify: `frontend/src/utils/scriptMapping.js`
- Modify: `frontend/src/components/StepEditor.vue`
- Create: `frontend/src/components/ElementPickerDialog.vue`

- [ ] **Step 1: scriptMapping.js 带绑定字段**

`fromPipelineMapping` 返回行加字段（保持现有逻辑不动，只加字段）：

```js
  return [{
    seq: m.step || 0, action,
    target: action === 'navigate' ? '' : (extractLocator(m.impl) || m.element_name || ''),
    value: m.value || '',
    element_name: m.element_name || '',
    expected: (assertExpected && assertValid) ? assertExpected : '',
    // 方案V1：绑定溯源字段
    element_id: m.element_id || '',
    match_level: m.match_level || '',
    match_score: m.match_score ?? null,
    case_step_no: m.step || null,
    case_target_text: m.target || '',   // 用例目标词原文（synonym 回写源）
  }]
```

（pipeline 的 step_mapping 里需有 element_id/match_level/match_score——Task 3 的 ActionWithLocator 已带，确认 Step4 落 step_mapping 时透传这些字段，若 GenerateResult 落库处有字段白名单需同步加。）

- [ ] **Step 2: ElementPickerDialog.vue 新建**

```vue
<template>
  <el-dialog v-model="visible" title="选择元素" width="640px" destroy-on-close>
    <el-input v-model="query" placeholder="搜索别名/文本" clearable class="mb-3" @input="load" />
    <el-collapse v-model="activePages">
      <el-collapse-item v-for="pg in pages" :key="pg.page_id" :title="pg.page_name" :name="pg.page_id">
        <el-table :data="pg.elements" size="small" highlight-current-row @current-change="onPick">
          <el-table-column prop="element_name" label="别名" min-width="140" />
          <el-table-column prop="locator" label="首选定位" min-width="200" show-overflow-tooltip />
          <el-table-column prop="confidence" label="置信度" width="80" />
        </el-table>
      </el-collapse-item>
    </el-collapse>
  </el-dialog>
</template>

<script setup>
// 方案V1：元素绑定选择器（Cypress Selector Playground 思路：候选可见、可切换）
import { ref } from 'vue'
import request from '@/utils/request'

const visible = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['pick'])
const props = defineProps({ projectId: { type: String, required: true } })

const pages = ref([])
const query = ref('')
const activePages = ref([])

async function load() {
  const { data } = await request.get('/elements/picker', {
    params: { project_id: props.projectId, q: query.value || undefined },
  })
  pages.value = data.pages || []
  activePages.value = pages.value.map((p) => p.page_id)
}

function onPick(row) {
  if (!row) return
  emit('pick', row)
  visible.value = false
}

defineExpose({ load })
</script>
```

（`defineModel` 需 Vue3.4+；若项目版本低改用 `v-model:visible` + computed 代理——执行时看 package.json vue 版本决定。）

- [ ] **Step 3: StepEditor.vue 元素格改造**

元素列（现有 19-25 行的手填输入框）改为：绑定态显示 `别名 + 定位`，未绑定显示红色"待选择"tag，点击弹选择器。核心改动（保留行式表格结构）：

```vue
<!-- 元素列：绑定显示 / 待选择标记 -->
<template #default="{ row }">
  <el-tag v-if="!row.element_id" type="danger" effect="light" style="cursor:pointer"
          @click="openPicker(row)">待选择</el-tag>
  <div v-else style="cursor:pointer" @click="openPicker(row)">
    <div>{{ row.element_name }}</div>
    <div class="text-xs text-gray-400">{{ row.target }}</div>
  </div>
</template>
```

```js
const pickerVisible = ref(false)
const pickerRow = ref(null)
function openPicker(row) {
  pickerRow.value = row
  pickerVisible.value = true
}
function onPicked(el) {
  Object.assign(pickerRow.value, {
    element_id: el.element_id,
    element_name: el.element_name,
    target: el.locator,
  })
}
```

辅元素列：仅 `row.action === 'input_captcha'` 时显示第二格（同样走选择器，写入 `row.extra_target`/`row.extra_element_id`）。

- [ ] **Step 4: 手动验证（前端起服务）**

Run: `cd frontend && npm run dev`，进脚本编辑器确认：待选择 tag 显示、弹窗分组搜索可用、选中后格子更新、input_captcha 行出现辅元素格。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/scriptMapping.js frontend/src/components/StepEditor.vue frontend/src/components/ElementPickerDialog.vue
git commit -m "feat(frontend): StepEditor元素绑定选择器+待选择标记+辅元素列 — 方案V1阶段9"
```

---

## Task 10: 结构调整——回归并入测试集 + 脚本库溯源列 + 执行记录增强

**Files:**
- Modify: `backend/app/models/test_set.py:20`、`backend/app/api/v1/test_sets.py:18`（source 枚举）
- Modify: `frontend/src/router/index.js:96-98`、`frontend/src/layouts/MainLayout.vue:48`（删回归页路由/菜单）
- Modify: `frontend/src/views/AutoUITest.vue`（工具栏加"AI识别回归"按钮 + source 标签）
- Modify: `backend/app/api/v1/scripts.py`（list 加绑定用例/被引用数聚合）
- Modify: `backend/app/models/execution.py`、`backend/app/api/v1/reports.py`（bug 表+软删）
- Test: `backend/tests/test_struct_adjust.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""结构调整测试（方案V1 阶段10）：source枚举/引用计数/bug软删。"""
import pytest


def test_test_set_source_enum_includes_regression():
    from app.api.v1.test_sets import TestSetCreate  # 实际类名执行时核对
    import pydantic
    # 合法
    TestSetCreate(project_id="p", name="n", source="ai_regression")
    with pytest.raises(pydantic.ValidationError):
        TestSetCreate(project_id="p", name="n", source="bad_source")


@pytest.mark.asyncio
async def test_script_list_includes_ref_counts(client, monkeypatch):
    resp = await client.get("/api/v1/scripts", params={"project_id": "p1"})
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert "bound_case" in item and "test_set_refs" in item


@pytest.mark.asyncio
async def test_execution_soft_delete(client):
    resp = await client.delete("/api/v1/reports/records/rec-1")
    assert resp.status_code in (200, 204)
```

（API 测试细节按现有 conftest 的 client/monkeypatch 模式落地，类名/表名执行时核对。）

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && venv/Scripts/python -m pytest tests/test_struct_adjust.py -v`
Expected: FAIL

- [ ] **Step 3: 后端实现**

1. source 枚举：`test_sets.py:18` pattern 改 `^(manual|ai_suggest|convert_page|ai_regression|manual_regression)$`；`test_set.py:20` 注释同步。
2. scripts list：SQL 加两个子查询聚合——`bound_case`（join test_cases 取 case_step_no 对应用例名，或直接返回 script.case_id 若 ScriptAsset 有绑定列——执行时 grep ScriptAsset 字段确认）、`test_set_refs`（COUNT test_set 关联表）。
3. 执行记录软删：execution.py 的 ExecutionRecord 加 `is_deleted = Column(Boolean, default=False)`；reports.py 加：

```python
@router.delete("/records/{record_id}")
async def delete_record(record_id: str, db: AsyncSession = Depends(get_db)):
    rec = await db.get(ExecutionRecord, UUID(record_id))
    if not rec:
        raise HTTPException(404, "记录不存在")
    rec.is_deleted = True
    await db.commit()
    return {"ok": True}
```

4. bug 条目：`execution.py` 加 `ExecutionBug` 模型（record_id FK, step_snapshot JSONB, screenshot_url, error_stack, ai_diagnosis Text）；reports 失败落库处（grep 失败记录写入点）自动生成 bug 行；ReportDetail 数据源带出 bugs。

- [ ] **Step 4: 前端实现**

1. 删路由 `router/index.js:96-98` 回归项 + `MainLayout.vue:48` 菜单项；Regression.vue 里与 AutoUITest 不重合的功能（AI识别回归按钮）迁移：AutoUITest.vue 测试集工具栏加按钮，调现有回归识别 API，产物 source=ai_regression。source 标签展示加映射：`ai_regression→'AI识别回归'`、`manual_regression→'手工回归'`。
2. 脚本库 Tab（AutoUITest.vue 内）加两列：绑定用例（bound_case）、被N测试集引用（test_set_refs）。
3. ReportDetail.vue 加 bug 清单面板 + 失败行"AI诊断"按钮（已有 `/diagnose` 接线）+ 记录删除按钮。

- [ ] **Step 5: 跑通过 + 全量回归 + 前端 build**

Run: `cd backend && venv/Scripts/python -m pytest && cd ../frontend && npm run build`
Expected: 全 PASS、build 成功

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/test_set.py backend/app/api/v1/test_sets.py backend/app/api/v1/scripts.py backend/app/models/execution.py backend/app/api/v1/reports.py backend/tests/test_struct_adjust.py frontend/src/router/index.js frontend/src/layouts/MainLayout.vue frontend/src/views/AutoUITest.vue frontend/src/views/reports/ReportDetail.vue
git commit -m "feat: 回归并入测试集(source枚举)+脚本库溯源列+执行记录bug清单/软删 — 方案V1阶段10"
```

---

## 收尾

- [ ] 全量测试：`cd backend && venv/Scripts/python -m pytest`（基线 770+，目标全绿）
- [ ] 前端 build：`cd frontend && npm run build`
- [ ] 对照 spec 七节验收标准逐项勾验（登录用例 7 步实测：6 步绑定、synonym 二次命中、SSE 直播、回归菜单消失、执行记录 bug 清单）
- [ ] 更新 `docs/SESSION_HANDOFF` 存档 + memory

## 验收标准（来自 spec 第七节）

1. 登录用例 7 步转换：≥6 步绑定为库内元素，值/期望值与用例逐行一致
2. 未命中步骤"待选择"红标 + 选择器绑定可保存
3. 人工绑定后二次转换同目标词 L2 直接命中（synonym 生效）
4. 生成代码与步骤表逐行对应，无 LLM 自由发挥
5. 回归菜单消失，测试集来源标签含"AI识别回归"
6. 执行记录含 bug 清单、可删除、失败行有 AI 诊断入口
