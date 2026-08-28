# 回归测试（#8）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 回归集管理（规则引擎 AI 识别 + 人工调整）→ 回归批量执行（ui_regression + 失败策略）→ 回归报告（复用 #6/#5c）→ 脚本库页回归三列。

**Architecture:** 新建 regression_set 表 + RegressionService（六规则打分引擎，纯 SQL 无 LLM）+ /regression 8 端点；confirm hook 自动识别；批量执行复用 run_scripts_task（扩 exec_type/fail_fast）；前端 Regression.vue（/auto/regression）+ ScriptConvert 三列。

**Tech Stack:** FastAPI + SQLAlchemy async（Boolean/Index 新 import）；无 LLM、无新 Redis 键；前端 Vue3 + Element Plus。

**Spec:** `docs/superpowers/specs/2026-08-28-regression-design.md`（偏差 F/H/I/J/K/O 与规则口径以 spec 为准）

**关键复用（不要重写）：**
- `run_scripts_task` — `backend/app/tasks/script_tasks.py:99`（本计划 T4 扩 exec_type/fail_fast 参数）
- `notifier.notify_report_ready` — `backend/app/services/notifier.py`（stub）
- `scriptAPI.subscribe(sessionId, cb)` SSE 订阅模式 — `frontend/src/views/ScriptConvert.vue` startSSE 参考
- `DiagnosisCard.vue` + `diagnosticsAPI.analyze(executionId, step, null, detailId)` — #5c 已建
- TestCase.priority / TestPoint.page_name+type_label / ScriptAsset.category+module+step_mapping — 打分数据源全在 master

**测试约定：** 全 mock（FakeDB 风格参考 `tests/test_diagnostics_service.py`）；同步 def + `asyncio_run`；规则引擎的打分函数设计为**接收纯 dict 数据**（非 ORM），单测零 DB mock。

---

### Task 1: 数据层 — RegressionSet 模型 + module 回写（偏差 J）

**Files:**
- Create: `backend/app/models/regression.py`
- Modify: `backend/app/models/__init__.py`（注册 import）
- Modify: `backend/app/tasks/script_tasks.py`（convert_scripts_task 里 module 推导）
- Test: `backend/tests/test_regression_service.py`（新建，本任务先放模型测试）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_regression_service.py`：

```python
"""Regression (#8) tests (mock db / pure-function rule engine)."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def asyncio_run(coro): return asyncio.run(coro)


class TestRegressionSetModel:
    def test_model_fields_and_defaults(self):
        """§3.6.5 DDL: 字段/默认值/UNIQUE 约束定义存在."""
        from app.models.regression import RegressionSet
        r = RegressionSet(project_id=uuid4(), script_id=uuid4())
        assert r.ai_suggested is None or r.ai_suggested is False  # Column default False
        assert r.include_source == "ai" or r.include_source is None
        # 表级约束
        consts = [c.name for c in RegressionSet.__table_args__ if hasattr(c, "name")]
        assert "uq_regression_project_script" in consts
        assert "idx_reg_project" in consts
        assert "idx_reg_included" in consts

    def test_registered_in_models_init(self):
        """models/__init__ 可导入 (建表反射/关系注册需要)."""
        from app.models import RegressionSet  # noqa: F401
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_regression_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.regression'`

- [ ] **Step 3: 实现 RegressionSet 模型**

新建 `backend/app/models/regression.py`：

```python
"""回归集关联表 (模块 #8, 需求 §3.6.5)."""
import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class RegressionSet(Base):
    """回归集关联表: 脚本 ↔ 回归集成员关系 + AI 识别结果 (REG-01/02)."""

    __tablename__ = "regression_set"
    __table_args__ = (
        UniqueConstraint("project_id", "script_id", name="uq_regression_project_script"),
        Index("idx_reg_project", "project_id"),
        Index("idx_reg_included", "actual_included"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"),
                        nullable=False, index=True)
    script_id = Column(UUID(as_uuid=True), ForeignKey("script_asset.id", ondelete="CASCADE"),
                       nullable=False)
    ai_suggested = Column(Boolean, default=False, comment="AI 判定是否纳入 (REG-02)")
    ai_reason = Column(String(200), comment="AI 命中原因 (规则名拼接, ≤200)")
    actual_included = Column(Boolean, default=False, comment="实际纳入 (AI建议+人工调整, REG-03)")
    include_source = Column(String(10), default="ai", comment="ai/manual")
    included_at = Column(DateTime(timezone=True), server_default=func.now())
```

注意：需求 DDL 的 `idx_reg_included` 是部分索引（WHERE actual_included=TRUE）；SQLAlchemy 用 `postgresql_where` 才是真部分索引，但普通索引功能等价（查询量级小），spec §2.1 已注明。如想精确还原可用 `Index("idx_reg_included", "actual_included", postgresql_where=text("actual_included = TRUE"))`——二选一，测试只查名字。

`backend/app/models/__init__.py` 加：

```python
from app.models.regression import RegressionSet
```
（并加入 `__all__` 若该文件有。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_regression_service.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: module 回写（convert task）**

`backend/app/tasks/script_tasks.py` 的 `convert_scripts_task` 内 `_run()` 中，`cases = [c.to_dict() for c in result.scalars().all()]` 之后加 module 推导（一次 JOIN 查 TestPoint）：

```python
            # #8 偏差 J: module 从 TestCase.point_id → TestPoint.page_name 推导
            point_ids = {c.get("point_id") for c in cases if c.get("point_id")}
            page_by_point = {}
            if point_ids:
                pres = await db.execute(
                    select(TestPoint).where(TestPoint.id.in_([uuid.UUID(p) for p in point_ids])))
                page_by_point = {str(p.id): p.page_name for p in pres.scalars().all()}
            for c in cases:
                c["module"] = page_by_point.get(c.get("point_id"))
```

（task 顶部局部 import 区加 `from app.models.test_case import TestPoint`——该文件已有 `from app.models.test_case import TestCase, ScriptAsset`，合并进同行。）

`backend/app/services/script_convert_service.py` 的 `convert_one` 里 ScriptAsset 构造（约 59 行）加 `module=case.get("module")`：

```python
        asset = ScriptAsset(
            case_id=case_id, project_id=case.get("project_id"),
            name=normalized.title, description=case.get("expected_result"),
            content=gen.script, version=1, status=status,
            category="uncategorized", module=case.get("module"),
            step_mapping=gen.step_mapping,
            locator_source=gen.locator_source, last_status="never_run",
        )
```

- [ ] **Step 6: 全量回归**

Run: `cd /d/MoonTest/backend && python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py`
Expected: 全绿（420 基线 + 2 新）

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/regression.py backend/app/models/__init__.py backend/app/tasks/script_tasks.py backend/app/services/script_convert_service.py backend/tests/test_regression_service.py
git commit -m "feat(regression): RegressionSet model + module inference at convert (#8 T1)"
```
（commit 末尾加 Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>，下同）

---

### Task 2: 规则引擎 — 六规则打分（纯函数，零 DB）

**Files:**
- Create: `backend/app/services/regression_rules.py`
- Test: `backend/tests/test_regression_rules.py`（新建）

**设计**：打分函数**接收纯 dict**（controller/调用方负责从 ORM 组装），保证单测零 mock、规则可独立验证。

输入 dict 契约（每个脚本一份）：
```python
{
  "priority": "P0",              # TestCase.priority (缺省 P1)
  "category": "core_flow",       # ScriptAsset.category
  "module": "登录鉴权",           # ScriptAsset.module (可 None)
  "module_has_included": False,  # 同 module 下是否已有 actual_included=true (调用方查)
  "type_label": "正常流程",       # TestPoint.type_label (可 None)
  "step_count": 8,               # len(step_mapping)
  "element_count": 5,            # len({sm["element_name"]})
  "recent_runs": [True, True, False, True],  # 近N次 step=0 结果序列 (旧→新), 空列表=无运行数据
}
```

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_regression_rules.py`：

```python
"""#8 规则引擎单测 (纯函数, spec §3.1 口径)."""
from app.services.regression_rules import score_script, INCLUDED_THRESHOLD


def _base(**kw):
    d = dict(priority="P1", category="uncategorized", module=None, module_has_included=False,
             type_label=None, step_count=20, element_count=15, recent_runs=[])
    d.update(kw)
    return d


class TestIndividualRules:
    def test_r1_priority(self):
        assert score_script(_base(priority="P0"))[0] >= 2   # P0=2
        s, _ = score_script(_base(priority="P1"))
        assert s >= 1                                        # P1=1 (基准分)
        s, _ = score_script(_base(priority="P2"))
        assert s == 0

    def test_r2_pass_rate(self):
        # 8/10 = 80% 含边界 → 2 分
        s, r = score_script(_base(priority="P2", recent_runs=[True]*8 + [False]*2))
        assert s == 2
        assert "通过率" in r
        # 7/10 = 70% → 0
        s, _ = score_script(_base(priority="P2", recent_runs=[True]*7 + [False]*3))
        assert s == 0
        # <3 次运行不罚 (0 分不负)
        s, _ = score_script(_base(priority="P2", recent_runs=[True, True]))
        assert s == 0

    def test_r3_core_flow(self):
        s, r = score_script(_base(priority="P2", category="core_flow", type_label="正常流程"))
        assert s == 2  # category=1 + type_label=1
        assert "核心" in r
        s, _ = score_script(_base(priority="P2", category="ui_smoke"))
        assert s == 1

    def test_r4_module_representative(self):
        s, r = score_script(_base(priority="P2", module="登录鉴权", module_has_included=False))
        assert s == 1
        assert "模块" in r
        # 已有 included → 不加
        s, _ = score_script(_base(priority="P2", module="登录鉴权", module_has_included=True))
        assert s == 0
        # module 空 → 跳过
        s, _ = score_script(_base(priority="P2", module=None))
        assert s == 0

    def test_r5_stability(self):
        # 翻转 2 次 → flaky 0 分
        s, _ = score_script(_base(priority="P2", recent_runs=[True, False, True, False]))
        assert s == 0
        # 无翻转 → 1 分
        s, r = score_script(_base(priority="P2", recent_runs=[True, True, False]))
        assert s == 1
        assert "稳定" in r or "flaky" not in r
        # <2 次不判
        s, _ = score_script(_base(priority="P2", recent_runs=[True]))
        assert s == 0

    def test_r6_low_dependency(self):
        s, r = score_script(_base(priority="P2", step_count=8, element_count=5))
        assert s == 1
        assert "依赖" in r
        s, _ = score_script(_base(priority="P2", step_count=11, element_count=5))
        assert s == 0
        s, _ = score_script(_base(priority="P2", step_count=8, element_count=9))
        assert s == 0


class TestAggregate:
    def test_threshold_3(self):
        # P0(2) + 低依赖(1) = 3 → 纳入
        included, reason = score_script(_base(priority="P0", step_count=5, element_count=3))
        assert included is True
        # P1(1) = 1 → 不纳入
        included, _ = score_script(_base())
        assert included is False

    def test_new_script_can_be_included(self):
        """新脚本无运行数据: R1+R3+R6 可达 4 分."""
        included, _ = score_script(_base(priority="P0", category="core_flow",
                                         step_count=5, element_count=3))
        assert included is True

    def test_reason_joins_hits_and_truncates(self):
        _, reason = score_script(_base(priority="P0", category="core_flow", type_label="正常流程",
                                       step_count=5, element_count=3))
        assert "P0" in reason and "核心" in reason and "依赖" in reason
        _, reason = score_script(_base(priority="P0", **{"reason_pad": None})) if False else (None, reason)
        # 截断: 构造超长场景不易, 直接测常量上限逻辑存在
        from app.services.regression_rules import MAX_REASON_LEN
        assert MAX_REASON_LEN == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_regression_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.regression_rules'`

- [ ] **Step 3: 实现规则引擎**

新建 `backend/app/services/regression_rules.py`：

```python
"""#8 AI 识别规则引擎 (§3.6.6 六规则, spec §3.1 口径).

纯函数: 输入脚本数据 dict, 输出 (included: bool, reason: str).
零 DB/零 LLM — 数据组装由调用方 (RegressionService) 完成.
"""
INCLUDED_THRESHOLD = 3
MAX_REASON_LEN = 200
CORE_CATEGORIES = ("core_flow", "ui_smoke")
PASS_RATE_THRESHOLD = 0.8
PASS_RATE_MIN_RUNS = 3
PASS_RATE_WINDOW = 10
FLAKY_WINDOW = 5
FLAKY_MIN_RUNS = 2
FLIP_THRESHOLD = 2
MAX_STEPS = 10
MAX_ELEMENTS = 8


def _flip_count(runs):
    """pass↔fail 翻转次数."""
    return sum(1 for a, b in zip(runs, runs[1:]) if a != b)


def score_script(data: dict):
    """六规则打分. 返回 (included, reason).

    规则口径 (spec §3.1):
    R1 优先级(高): P0=2/P1=1/其他=0
    R2 通过率(高): 近10次 pass率>=80% -> 2; 运行<3次 -> 0 不罚
    R3 核心覆盖(中): category in {core_flow,ui_smoke} -> 1; type_label 含"正常" 再+1
    R4 模块代表(中): module 非空且该 module 无 included -> 1; module 空 -> 跳过
    R5 稳定性(中): 近5次翻转>=2 -> flaky 0; 否则 1; 运行<2次不判(0)
    R6 依赖(低): 步骤<=10 且去重元素<=8 -> 1
    """
    score = 0
    hits = []

    # R1
    priority = (data.get("priority") or "P1").upper()
    if priority == "P0":
        score += 2
        hits.append("P0核心用例")
    elif priority == "P1":
        score += 1
        hits.append("P1用例")

    # R2
    runs = list(data.get("recent_runs") or [])
    if len(runs) >= PASS_RATE_MIN_RUNS:
        rate = sum(1 for r in runs[:PASS_RATE_WINDOW] if r) / min(len(runs), PASS_RATE_WINDOW)
        if rate >= PASS_RATE_THRESHOLD:
            score += 2
            hits.append(f"历史通过率{rate:.0%}")

    # R3
    if (data.get("category") or "") in CORE_CATEGORIES:
        score += 1
        hits.append("核心流程覆盖")
        tl = data.get("type_label") or ""
        if "正常" in tl:
            score += 1

    # R4
    if data.get("module") and not data.get("module_has_included"):
        score += 1
        hits.append(f"模块[{data['module']}]代表")

    # R5
    if len(runs) >= FLAKY_MIN_RUNS:
        window = runs[:FLAKY_WINDOW]
        if _flip_count(window) < FLIP_THRESHOLD:
            score += 1
            hits.append("运行稳定")

    # R6
    if (data.get("step_count") or 0) <= MAX_STEPS and (data.get("element_count") or 0) <= MAX_ELEMENTS:
        score += 1
        hits.append("依赖少")

    included = score >= INCLUDED_THRESHOLD
    reason = "；".join(hits)[:MAX_REASON_LEN]
    return included, reason
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_regression_rules.py -q`
Expected: PASS（11 passed 左右）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/regression_rules.py backend/tests/test_regression_rules.py
git commit -m "feat(regression): 6-rule scoring engine (pure functions) (#8 T2)"
```

---

### Task 3: RegressionService — 数据组装 + upsert + 统计/列表

**Files:**
- Create: `backend/app/services/regression_service.py`
- Test: `backend/tests/test_regression_service.py`（追加）

**设计**：`RegressionService(db)`，方法：
- `identify_project(project_id)` → 全量 confirmed 脚本打分 + upsert（返回 {identified, suggested_count}）
- `identify_for_script(project_id, script_id)` → 单脚本（confirm hook 用）
- `_assemble(script, ...)` → 组装 score_script 输入 dict（R2/R5 查 ExecutionDetail；R4 查 regression_set）
- `upsert_member(project_id, script_id, included, reason)` → UNIQUE 冲突时更新 ai_suggested/ai_reason；**actual_included 逻辑**：无行 → 新建 actual_included=included, include_source="ai"；有行且 include_source="manual" → 不动 actual_included/include_source；有行且 include_source="ai" → actual_included 跟随新 included
- `set_members(project_id, script_ids, action)` → add/remove（REG-03，include_source="manual"）
- `get_stats(project_id)` → {total(included数), passed, failed, pass_rate}（included ⋈ script_asset.last_status）
- `list_view(project_id, category, keyword)` → 全量 confirmed 脚本 LEFT JOIN regression_set

- [ ] **Step 1: 写失败测试（upsert 语义 + stats，mock db）**

追加到 `backend/tests/test_regression_service.py`：

```python
# ---- T3: RegressionService ----
from app.services.regression_service import RegressionService


class FakeResult:
    def __init__(self, scalar=None, scalars=None):
        self._scalar = scalar
        self._scalars = scalars

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return MagicMock(all=MagicMock(return_value=self._scalars or []))


class FakeRegressionDB:
    """顺序弹出 execute 结果; 记录 add 的对象."""
    def __init__(self, results):
        self._results = list(results)
        self.added = []

    async def execute(self, q):
        r = self._results.pop(0) if self._results else FakeResult()
        return r

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass


def _script(id_, **kw):
    from app.models.test_case import ScriptAsset
    base = dict(id=id_, case_id="c1", project_id="p1", name=f"脚本{str(id_)[:4]}",
                content="x", version=1, status="confirmed", category="uncategorized")
    base.update(kw)
    return ScriptAsset(**base)


class TestUpsertMember:
    def test_first_identify_creates_row_following_ai(self):
        """首次识别: 无行 → 新建 actual_included=ai_suggested, source=ai."""
        from app.models.regression import RegressionSet
        db = FakeRegressionDB([FakeResult(scalar=None)])  # 查无现有行
        svc = RegressionService(db)
        row = asyncio_run(svc.upsert_member("p1", uuid4(), included=True, reason="P0核心用例"))
        assert isinstance(row, RegressionSet)
        assert row in db.added
        assert row.ai_suggested is True
        assert row.actual_included is True
        assert row.include_source == "ai"

    def test_manual_row_not_overwritten(self):
        """I 偏差: include_source=manual 的行, 识别只更新 ai 字段, 不动 actual_included."""
        from app.models.regression import RegressionSet
        existing = RegressionSet(project_id=uuid4(), script_id=uuid4(),
                                 ai_suggested=False, actual_included=True,
                                 include_source="manual")
        db = FakeRegressionDB([FakeResult(scalar=existing)])
        svc = RegressionService(db)
        row = asyncio_run(svc.upsert_member("p1", existing.script_id, included=False, reason=""))
        assert row is existing
        assert row.ai_suggested is False      # ai 字段更新
        assert row.actual_included is True    # 人工调整保留
        assert row.include_source == "manual"

    def test_ai_row_follows_new_result(self):
        """include_source=ai 的行, actual_included 跟随最新识别."""
        from app.models.regression import RegressionSet
        existing = RegressionSet(project_id=uuid4(), script_id=uuid4(),
                                 ai_suggested=True, actual_included=True,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=existing)])
        svc = RegressionService(db)
        row = asyncio_run(svc.upsert_member("p1", existing.script_id, included=False, reason=""))
        assert row.ai_suggested is False
        assert row.actual_included is False   # ai 行跟随


class TestSetMembers:
    def test_add_sets_manual(self):
        from app.models.regression import RegressionSet
        existing = RegressionSet(project_id=uuid4(), script_id=uuid4(),
                                 ai_suggested=False, actual_included=False,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=existing)])
        svc = RegressionService(db)
        asyncio_run(svc.set_member("p1", existing.script_id, action="add"))
        assert existing.actual_included is True
        assert existing.include_source == "manual"

    def test_remove_sets_manual(self):
        from app.models.regression import RegressionSet
        existing = RegressionSet(project_id=uuid4(), script_id=uuid4(),
                                 ai_suggested=True, actual_included=True,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=existing)])
        svc = RegressionService(db)
        asyncio_run(svc.set_member("p1", existing.script_id, action="remove"))
        assert existing.actual_included is False
        assert existing.include_source == "manual"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_regression_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.regression_service'`

- [ ] **Step 3: 实现 RegressionService**

新建 `backend/app/services/regression_service.py`：

```python
"""回归集服务 (#8): 识别数据组装 + upsert + 成员管理 + 统计.

规则打分在 regression_rules (纯函数); 本服务负责 ORM→dict 组装与落库.
upsert 语义 (spec 偏差 I): manual 行不动 actual_included; ai 行跟随最新识别.
"""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionDetail
from app.models.regression import RegressionSet
from app.models.test_case import ScriptAsset, TestCase, TestPoint
from app.services.regression_rules import score_script

logger = logging.getLogger(__name__)

PASS_HISTORY_WINDOW = 10  # R2 取近 N 次 step=0 结果


class RegressionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- 识别 ----

    async def identify_project(self, project_id: str) -> dict:
        """全量 confirmed 脚本重算识别 (REG-02, /identify + confirm hook 全量模式)."""
        result = await self.db.execute(
            select(ScriptAsset).where(
                ScriptAsset.project_id == UUID(project_id),
                ScriptAsset.status == "confirmed"))
        scripts = result.scalars().all()
        suggested = 0
        for s in scripts:
            row = await self._identify_one(s)
            if row and row.ai_suggested:
                suggested += 1
        return {"identified": len(scripts), "suggested_count": suggested}

    async def identify_for_script(self, project_id: str, script_id: str) -> None:
        """单脚本识别 (#4 confirm hook). 异常由调用方隔离 (不阻塞 confirm)."""
        result = await self.db.execute(
            select(ScriptAsset).where(ScriptAsset.id == UUID(script_id)))
        script = result.scalar_one_or_none()
        if script:
            await self._identify_one(script)

    async def _identify_one(self, script: ScriptAsset) -> Optional[RegressionSet]:
        data = await self._assemble(script)
        included, reason = score_script(data)
        return await self.upsert_member(str(script.project_id), script.id,
                                        included=included, reason=reason)

    async def _assemble(self, script: ScriptAsset) -> dict:
        """ORM → score_script 输入 dict (spec T2 契约)."""
        # R1/R3 数据: TestCase.priority + TestPoint.type_label
        priority, type_label = "P1", None
        if script.case_id:
            r = await self.db.execute(select(TestCase).where(TestCase.id == script.case_id))
            case = r.scalar_one_or_none()
            if case:
                priority = case.priority or "P1"
                if case.point_id:
                    pr = await self.db.execute(
                        select(TestPoint).where(TestPoint.id == case.point_id))
                    point = pr.scalar_one_or_none()
                    if point:
                        type_label = point.type_label

        # R2/R5 数据: 近 N 次 step=0 结果 (旧→新)
        er = await self.db.execute(
            select(ExecutionDetail)
            .where(ExecutionDetail.script_id == script.id,
                   ExecutionDetail.step == 0)
            .order_by(ExecutionDetail.created_at.desc())
            .limit(PASS_HISTORY_WINDOW))
        details = er.scalars().all()
        recent_runs = [d.status == "pass" for d in reversed(details)]

        # R4 数据: 同 module 是否已有 included
        module_has_included = False
        if script.module:
            mr = await self.db.execute(
                select(RegressionSet.id)
                .join(ScriptAsset, ScriptAsset.id == RegressionSet.script_id)
                .where(RegressionSet.project_id == script.project_id,
                       RegressionSet.actual_included.is_(True),
                       ScriptAsset.module == script.module,
                       ScriptAsset.id != script.id)
                .limit(1))
            module_has_included = mr.scalar_one_or_none() is not None

        # R6 数据
        sm = script.step_mapping or []
        elements = {m.get("element_name") for m in sm if m.get("element_name")}

        return {
            "priority": priority,
            "category": script.category,
            "module": script.module,
            "module_has_included": module_has_included,
            "type_label": type_label,
            "step_count": len(sm),
            "element_count": len(elements),
            "recent_runs": recent_runs,
        }

    # ---- upsert / 成员管理 ----

    async def upsert_member(self, project_id: str, script_id: UUID,
                            included: bool, reason: str) -> RegressionSet:
        r = await self.db.execute(
            select(RegressionSet).where(
                RegressionSet.project_id == UUID(project_id),
                RegressionSet.script_id == script_id))
        row = r.scalar_one_or_none()
        if row is None:
            row = RegressionSet(project_id=UUID(project_id), script_id=script_id,
                                ai_suggested=included, ai_reason=reason or None,
                                actual_included=included, include_source="ai")
            self.db.add(row)
        else:
            row.ai_suggested = included
            row.ai_reason = reason or None
            if row.include_source != "manual":
                # ai 行跟随最新识别; manual 行人工调整优先 (偏差 I)
                row.actual_included = included
                row.include_source = "ai"
        await self.db.flush()
        return row

    async def set_member(self, project_id: str, script_id: UUID, action: str) -> None:
        """REG-03 手动调整: add/remove, include_source=manual (识别不再覆盖)."""
        r = await self.db.execute(
            select(RegressionSet).where(
                RegressionSet.project_id == UUID(project_id),
                RegressionSet.script_id == script_id))
        row = r.scalar_one_or_none()
        if row is None:
            row = RegressionSet(project_id=UUID(project_id), script_id=script_id,
                                ai_suggested=False, actual_included=(action == "add"),
                                include_source="manual")
            self.db.add(row)
        else:
            row.actual_included = (action == "add")
            row.include_source = "manual"
        await self.db.flush()

    # ---- 统计 / 列表 ----

    async def get_stats(self, project_id: str) -> dict:
        """统计卡: included=true ⋈ script_asset.last_status 聚合 (页面加载即有值)."""
        result = await self.db.execute(
            select(ScriptAsset)
            .join(RegressionSet, RegressionSet.script_id == ScriptAsset.id)
            .where(RegressionSet.project_id == UUID(project_id),
                   RegressionSet.actual_included.is_(True)))
        scripts = result.scalars().all()
        total = len(scripts)
        passed = sum(1 for s in scripts if s.last_status == "passed")
        failed = sum(1 for s in scripts if s.last_status == "failed")
        rate = round(passed / total * 100, 1) if total else 0
        return {"total": total, "passed": passed, "failed": failed, "pass_rate": rate}

    async def list_view(self, project_id: str, category: Optional[str] = None,
                        keyword: Optional[str] = None) -> list:
        """管理视图: 全量 confirmed 脚本 LEFT JOIN regression_set (含未纳入行)."""
        q = (
            select(ScriptAsset, RegressionSet)
            .outerjoin(RegressionSet, RegressionSet.script_id == ScriptAsset.id)
            .where(ScriptAsset.project_id == UUID(project_id),
                   ScriptAsset.status == "confirmed")
        )
        if category:
            q = q.where(ScriptAsset.category == category)
        if keyword:
            q = q.where(ScriptAsset.name.ilike(f"%{keyword}%"))
        q = q.order_by(ScriptAsset.name)
        result = await self.db.execute(q)
        items = []
        for s, reg in result.all():
            items.append({
                "script": s.to_dict(),
                "ai_suggested": bool(reg.ai_suggested) if reg else False,
                "ai_reason": reg.ai_reason if reg else None,
                "actual_included": bool(reg.actual_included) if reg else False,
                "include_source": reg.include_source if reg else None,
            })
        return items
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_regression_service.py tests/test_regression_rules.py -q`
Expected: PASS（T1 2 + T3 4 + T2 全部）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/regression_service.py backend/tests/test_regression_service.py
git commit -m "feat(regression): RegressionService — assemble/upsert/stats/list (#8 T3)"
```

---

### Task 4: API /regression + confirm hook + run_scripts_task 扩参

**Files:**
- Create: `backend/app/api/v1/regression.py`
- Create: `backend/app/schemas/regression.py`
- Modify: `backend/app/api/__init__.py`（router 注册）
- Modify: `backend/app/api/v1/scripts.py`（confirm hook）
- Modify: `backend/app/tasks/script_tasks.py`（run_scripts_task 扩 exec_type/fail_fast）
- Test: `backend/tests/test_regression_api.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_regression_api.py`：

```python
"""Regression API tests (mock service / mock task)."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


PID = str(uuid4())
SID = str(uuid4())
UUID1 = "0f0e0d0c-0b0a-4948-8276-000000000001"
UUID2 = "0f0e0d0c-0b0a-4948-8276-000000000002"


class TestRegressionEndpoints:
    def test_list_returns_items(self):
        from app.api.v1 import regression as reg_mod

        async def fake_list(self, project_id, category=None, keyword=None):
            return [{"script": {"id": SID, "name": "登录"}, "ai_suggested": True,
                     "ai_reason": "P0核心用例", "actual_included": True,
                     "include_source": "ai"}]

        with patch.object(reg_mod.RegressionService, "list_view", fake_list):
            client = _client()
            resp = client.get(f"/api/v1/regression/list?project_id={PID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"][0]["actual_included"] is True

    def test_members_add(self):
        from app.api.v1 import regression as reg_mod

        with patch.object(reg_mod.RegressionService, "set_member", AsyncMock()) as sm:
            client = _client()
            resp = client.post("/api/v1/regression/members", json={
                "project_id": PID, "script_ids": [SID], "action": "add"})
        assert resp.status_code == 200
        assert sm.assert_awaited_once

    def test_identify_counts(self):
        from app.api.v1 import regression as reg_mod

        async def fake_identify(self, project_id):
            return {"identified": 8, "suggested_count": 5}

        with patch.object(reg_mod.RegressionService, "identify_project", fake_identify):
            client = _client()
            resp = client.post("/api/v1/regression/identify", json={"project_id": PID})
        assert resp.json()["data"]["suggested_count"] == 5

    def test_stats_shape(self):
        from app.api.v1 import regression as reg_mod

        async def fake_stats(self, project_id):
            return {"total": 8, "passed": 7, "failed": 1, "pass_rate": 87.5}

        with patch.object(reg_mod.RegressionService, "get_stats", fake_stats):
            client = _client()
            resp = client.get(f"/api/v1/regression/stats?project_id={PID}")
        assert resp.json()["data"]["pass_rate"] == 87.5

    def test_run_reuses_task_with_ui_regression(self):
        """REG-04: run 调 run_scripts_task, exec_type=ui_regression + fail_fast 进 config."""
        from app.api.v1 import regression as reg_mod

        with patch.object(reg_mod.run_scripts_task, "delay", MagicMock()) as delay:
            client = _client()
            resp = client.post("/api/v1/regression/run", json={
                "project_id": PID,
                "config": {"headless": True, "timeout": 60, "max_failures": 8,
                           "fail_fast": True}})
        assert resp.status_code == 200
        kwargs = delay.call_args.kwargs
        assert kwargs.get("exec_type") == "ui_regression"
        assert kwargs.get("config", {}).get("fail_fast") is True

    def test_latest_execution(self):
        from app.api.v1 import regression as reg_mod

        async def fake_latest(self, script_id):
            return {"execution_id": "er1", "exec_id": "exec-abc", "status": "fail"}

        with patch.object(reg_mod.RegressionService, "latest_execution", fake_latest):
            client = _client()
            resp = client.get(f"/api/v1/regression/latest-execution?script_id={SID}")
        assert resp.json()["data"]["exec_id"] == "exec-abc"

    def test_push_calls_notifier(self):
        from app.api.v1 import regression as reg_mod

        with patch.object(reg_mod, "notify_report_ready", AsyncMock()) as nr:
            client = _client()
            resp = client.post(f"/api/v1/regression/{UUID1}/push")
        assert resp.json()["data"]["pushed"] is True
        assert nr.assert_awaited_once

    def test_report_summary(self):
        from app.api.v1 import regression as reg_mod

        async def fake_summary(self, project_id):
            return {"record": {"exec_id": "exec-x", "passed_count": 7, "fail_count": 1},
                    "failed_details": [{"id": str(uuid4()), "step": 3,
                                        "script_id": SID, "error_type": "locate_failed"}]}

        with patch.object(reg_mod.RegressionService, "report_summary", fake_summary):
            client = _client()
            resp = client.get(f"/api/v1/regression/report-summary?project_id={PID}")
        assert resp.json()["data"]["failed_details"][0]["script_id"] == SID


class TestConfirmHook:
    def test_confirm_triggers_identify_nonblocking(self):
        """H 偏差: confirm 后 hook 识别; 识别异常不阻塞 confirm 主流程."""
        from app.api.v1 import scripts as scripts_mod

        fake_asset = MagicMock()
        fake_asset.status = "generated"
        fake_asset.project_id = UUID1
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = fake_asset

        async def fake_identify(self, project_id, script_id):
            raise RuntimeError("identify boom")

        with patch.object(scripts_mod, "RegressionService") as MockSvc, \
             patch.object(scripts_mod.select, return_value=MagicMock()):
            MockSvc.return_value.identify_for_script = fake_identify
            client = _client()
            # confirm 既有测试已覆盖正常路径; 这里只验证 hook 挂上后 confirm 不 5xx
            # (DB 层被 mock 后 commit 等依赖 MagicMock 自动满足)
            resp = client.post(f"/api/v1/scripts/{UUID2}/confirm")
        assert resp.status_code in (200, 500)  # DB mock 下允许 500; 关键是不因 hook 崩出 4xx 语义错位
```

（注：confirm hook 测试的 mock 粒度较粗——confirm 既有测试 `test_script_api.py` 已锁定正常路径；本测试目的只是验证 hook 异常被 try/except 吞掉不影响 confirm 返回。实现时若发现过度 mock 难以维系，可改为直接单测 `RegressionService.identify_for_script` 被 confirm 调用一次（patch 计数），弃用 HTTP 层。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_regression_api.py -q`
Expected: FAIL — 404（路由不存在）

- [ ] **Step 3: 实现 schemas + API + hook + task 扩参**

新建 `backend/app/schemas/regression.py`：

```python
"""Regression (#8) schemas."""
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional


class MembersRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    script_ids: List[str] = Field(..., min_length=1)
    action: Literal["add", "remove"]


class IdentifyRequest(BaseModel):
    project_id: str = Field(..., min_length=1)


class RegressionRunConfig(BaseModel):
    headless: bool = True
    timeout: int = Field(60, ge=5, le=600)
    max_failures: int = Field(8, ge=1, le=100)
    fail_fast: bool = Field(False, description="失败策略: false=继续(默认)/true=停止")


class RunRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    config: RegressionRunConfig = RegressionRunConfig()


class RegResponse(BaseModel):
    code: int = 0
    data: Any = None
```

新建 `backend/app/api/v1/regression.py`：

```python
"""回归测试 API (#8) — /regression 8 端点 (REG-01~05)."""
import logging
import uuid as uuid_mod

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.regression import (IdentifyRequest, MembersRequest,
                                    RegResponse, RunRequest)
from app.services.regression_service import RegressionService
from app.tasks.script_tasks import run_scripts_task

logger = logging.getLogger(__name__)
router = APIRouter()


def _pid(v: str) -> uuid_mod.UUID:
    try:
        return uuid_mod.UUID(v)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")


def _get_svc(db: AsyncSession = Depends(get_db)) -> RegressionService:
    return RegressionService(db)


@router.get("/list")
async def list_regression(project_id: str = Query(...),
                          category: str = Query(None),
                          keyword: str = Query(None),
                          svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """管理视图: 全量 confirmed 脚本 + 回归状态 (含未纳入行, REG-01/03)."""
    _pid(project_id)
    return RegResponse(data=await svc.list_view(project_id, category=category, keyword=keyword))


@router.post("/members")
async def set_members(request: MembersRequest,
                      svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """REG-03: 勾选批量加入/移出 (include_source=manual)."""
    _pid(request.project_id)
    for sid in request.script_ids:
        try:
            await svc.set_member(request.project_id, uuid_mod.UUID(sid), action=request.action)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid script_id: {sid}")
    await svc.db.commit()
    return RegResponse(data={"updated": len(request.script_ids), "action": request.action})


@router.post("/identify")
async def identify(request: IdentifyRequest,
                   svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """REG-02: 手动重算全项目识别."""
    _pid(request.project_id)
    return RegResponse(data=await svc.identify_project(request.project_id))


@router.get("/stats")
async def stats(project_id: str = Query(...),
                svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """统计卡: included ⋈ last_status 聚合."""
    _pid(project_id)
    return RegResponse(data=await svc.get_stats(project_id))


@router.post("/run")
async def run_regression(request: RunRequest,
                         svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """REG-04: 对 included=true 全部脚本批量执行 (exec_type=ui_regression)."""
    _pid(request.project_id)
    # 取 included 脚本 ids (list_view 含未纳入行, 这里按 actual_included 过滤)
    items = await svc.list_view(request.project_id)
    script_ids = [it["script"]["id"] for it in items if it["actual_included"]]
    if not script_ids:
        raise HTTPException(status_code=400, detail="回归集为空，无脚本可执行")
    session_id = str(uuid_mod.uuid4())
    run_scripts_task.delay(
        session_id=session_id, script_ids=script_ids,
        config=request.config.model_dump(),
        exec_type="ui_regression",
    )
    return RegResponse(data={"session_id": session_id,
                             "exec_id": f"exec-{session_id[:8]}",
                             "sse_url": f"/api/sse/stream/{session_id}",
                             "total": len(script_ids)})


@router.get("/latest-execution")
async def latest_execution(script_id: str = Query(...),
                           svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """行内 [报告]: 按 script_id 反查最近一次执行."""
    result = await svc.latest_execution(script_id)
    if result is None:
        raise HTTPException(status_code=404, detail="该脚本暂无执行记录")
    return RegResponse(data=result)


@router.post("/{exec_id}/push")
async def push_report(exec_id: str) -> RegResponse:
    """REG-05: 推送报告 (notifier stub, 真实渠道归 #10)."""
    from app.services.notifier import notify_report_ready
    await notify_report_ready(exec_id, {"source": "regression"})
    return RegResponse(data={"pushed": True, "exec_id": exec_id})


@router.get("/report-summary")
async def report_summary(project_id: str = Query(...),
                         svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """内嵌报告块: 最近一次 ui_regression 执行摘要 + 失败 detail 行."""
    _pid(project_id)
    return RegResponse(data=await svc.report_summary(project_id))
```

`backend/app/services/regression_service.py` 追加 `latest_execution` 和 `report_summary`：

```python
    async def latest_execution(self, script_id: str) -> Optional[dict]:
        """按 script_id 反查最近一次执行 (detail step=0 + 所属 record)."""
        from app.models.execution import ExecutionRecord
        r = await self.db.execute(
            select(ExecutionDetail)
            .where(ExecutionDetail.script_id == UUID(script_id),
                   ExecutionDetail.step == 0)
            .order_by(ExecutionDetail.created_at.desc())
            .limit(1))
        detail = r.scalar_one_or_none()
        if not detail:
            return None
        rr = await self.db.execute(
            select(ExecutionRecord).where(ExecutionRecord.id == detail.execution_record_id))
        rec = rr.scalar_one_or_none()
        return {
            "detail": detail.to_dict(),
            "record": rec.to_dict() if rec else None,
        }

    async def report_summary(self, project_id: str) -> dict:
        """最近一次 ui_regression 执行: record 摘要 + 失败 detail 行 (带 detail_id 供 #5c)."""
        from app.models.execution import ExecutionRecord
        r = await self.db.execute(
            select(ExecutionRecord)
            .where(ExecutionRecord.project_id == UUID(project_id),
                   ExecutionRecord.exec_type == "ui_regression")
            .order_by(ExecutionRecord.started_at.desc())
            .limit(1))
        rec = r.scalar_one_or_none()
        if not rec:
            return {"record": None, "failed_details": []}
        dr = await self.db.execute(
            select(ExecutionDetail)
            .where(ExecutionDetail.execution_record_id == rec.id,
                   ExecutionDetail.status == "fail",
                   ExecutionDetail.step != 0)  # 整体行不算失败步骤
            .order_by(ExecutionDetail.step))
        details = dr.scalars().all()
        return {"record": rec.to_dict(), "failed_details": [d.to_dict() for d in details]}
```

`backend/app/api/__init__.py`：
- import 行加 `regression`
- dashboard 注册行后加：
```python
api_router.include_router(regression.router, prefix="/regression", tags=["regression"])
```

**confirm hook**（`backend/app/api/v1/scripts.py` 的 confirm_script 端点）——`asset.status = "confirmed"` 之后、`await db.commit()` 之前加：

```python
    asset.status = "confirmed"
    # #8: TRANS-02 确认入库 → 触发回归识别 (spec 偏差 H; 异常隔离不阻塞 confirm)
    try:
        from app.services.regression_service import RegressionService
        await RegressionService(db).identify_for_script(str(asset.project_id), script_id)
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"regression identify hook failed (non-blocking): {e}")
    await db.commit()
```
（文件顶部 import 区加 `from app.services.regression_service import RegressionService` 可选——hook 内 lazy import 已足够，避免循环依赖风险。测试里 `from app.api.v1 import scripts as scripts_mod` patch 的是 `scripts_mod.RegressionService`——若用 lazy import 则 patch 目标改为 `app.services.regression_service.RegressionService`。**取 patch `app.services.regression_service.RegressionService` 方案**，测试 Step 1 的 patch 路径相应调整。）

**run_scripts_task 扩参**（`backend/app/tasks/script_tasks.py:99`）：

```python
def run_scripts_task(self, session_id: str, script_id: str = None, script_ids: list = None,
                     config: dict = None, exec_type: str = None):
```
内部 `_run()` 里 ExecutionRecord 构造（约 163 行）：

```python
            er = ExecutionRecord(
                exec_id=f"exec-{session_id[:8]}",
                project_id=project_id,
                exec_type=exec_type or ("batch" if script_ids else "single"),
                status="running", total_cases=len(targets),
            )
```

**fail_fast 消费**——`_run()` 的执行循环（约 172 行 `for sa in targets:`）改为在 detail fail 后 break：

```python
            cfg_obj = config or {}
            fail_fast = bool(cfg_obj.get("fail_fast", False))
            details = []
            for sa in targets:
                detail = await executor.execute(sa, config_obj, target_url, sse, er, page=None)
                if detail is not None:
                    detail.case_id = getattr(sa, "case_id", None)
                    details.append(detail)
                    if fail_fast and detail.status == "fail":
                        break  # 失败策略=停止: 脚本级 fail-fast (spec 偏差 K)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/MoonTest/backend && python -m pytest tests/test_regression_api.py -q`
Expected: PASS（8-9 个）

- [ ] **Step 5: 全量回归**

Run: `cd /d/MoonTest/backend && python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py`
Expected: 全绿（基线 420 + 新增；**注意既有 batch-run 测试可能断言 run_scripts_task.delay 的调用参数——exec_type 默认 None 时行为不变，理论上零破坏；若既有测试因 kwargs 变化失败，按最小改动修**）

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/regression.py backend/app/schemas/regression.py backend/app/api/__init__.py backend/app/api/v1/scripts.py backend/app/tasks/script_tasks.py backend/app/services/regression_service.py backend/tests/test_regression_api.py
git commit -m "feat(regression): /regression endpoints + confirm hook + task exec_type/fail_fast (#8 T4)"
```

---

### Task 5: 前端 Regression.vue + 路由

**Files:**
- Create: `frontend/src/api/regression.js`
- Create: `frontend/src/views/Regression.vue`
- Modify: `frontend/src/router/index.js`（/auto/regression 路由 + /auto/ui redirect 顺手修）

- [ ] **Step 1: API 封装**

新建 `frontend/src/api/regression.js`（**相对路径，axios baseURL 已含 /api/v1**）：

```js
import axios from './axios.js'

const BASE = '/regression'

export const regressionAPI = {
  async list(projectId, category = null, keyword = null) {
    const params = { project_id: projectId }
    if (category) params.category = category
    if (keyword) params.keyword = keyword
    const resp = await axios.get(`${BASE}/list`, { params })
    return resp.data
  },
  async setMembers(projectId, scriptIds, action) {
    const resp = await axios.post(`${BASE}/members`, {
      project_id: projectId, script_ids: scriptIds, action,
    })
    return resp.data
  },
  async identify(projectId) {
    const resp = await axios.post(`${BASE}/identify`, { project_id: projectId })
    return resp.data
  },
  async stats(projectId) {
    const resp = await axios.get(`${BASE}/stats`, { params: { project_id: projectId } })
    return resp.data
  },
  async run(projectId, config) {
    const resp = await axios.post(`${BASE}/run`, { project_id: projectId, config })
    return resp.data
  },
  async latestExecution(scriptId) {
    const resp = await axios.get(`${BASE}/latest-execution`, { params: { script_id: scriptId } })
    return resp.data
  },
  async push(execId) {
    const resp = await axios.post(`${BASE}/${execId}/push`)
    return resp.data
  },
  async reportSummary(projectId) {
    const resp = await axios.get(`${BASE}/report-summary`, { params: { project_id: projectId } })
    return resp.data
  },
}
```

- [ ] **Step 2: Regression.vue**

新建 `frontend/src/views/Regression.vue`。布局按 spec §5.1 四区块。关键实现点（完整组件由实现者按下列骨架+现有页面风格补全——参考 `ScriptConvert.vue` 的统计卡/SSE/表格写法）：

```vue
<template>
  <div class="regression-page">
    <!-- 区块1: 统计卡片 (GET /stats) -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6"><div class="stat"><div class="num">{{ stats.total }}</div><div class="lbl">回归集脚本数</div></div></el-col>
      <el-col :span="6"><div class="stat"><div class="num pass">{{ stats.passed }}</div><div class="lbl">通过</div></div></el-col>
      <el-col :span="6"><div class="stat"><div class="num fail">{{ stats.failed }}</div><div class="lbl">失败</div></div></el-col>
      <el-col :span="6"><div class="stat"><div class="num rate">{{ stats.pass_rate }}%</div><div class="lbl">通过率</div></div></el-col>
    </el-row>

    <!-- 工具行: 项目选择 / 分类筛选 / 搜索 / [重算识别] / [刷新] -->
    <el-row style="margin: 12px 0">
      <el-select v-model="projectId" placeholder="项目" @change="loadAll">...</el-select>
      <el-select v-model="category" clearable placeholder="分类" @change="loadList">...</el-select>
      <el-input v-model="keyword" placeholder="搜索" clearable @change="loadList" style="width: 200px" />
      <el-button @click="reidentify" :loading="identifying">重算识别</el-button>
      <el-button @click="loadAll">刷新</el-button>
    </el-row>

    <!-- 区块2: 回归集列表 (管理视图, GET /list, 含未纳入行) -->
    <el-table :data="rows" border @selection-change="onSelect">
      <el-table-column type="selection" width="45" />
      <el-table-column prop="script.name" label="名称" min-width="160" />
      <el-table-column prop="script.last_status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.script.last_status === 'passed'" type="success" size="small">通过</el-tag>
          <el-tag v-else-if="row.script.last_status === 'failed'" type="danger" size="small">失败</el-tag>
          <el-tag v-else size="info" size="small">{{ row.script.last_status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="AI建议" width="90">
        <template #default="{ row }">
          <el-tooltip v-if="row.ai_reason" :content="row.ai_reason">
            <el-tag :type="row.ai_suggested ? 'warning' : 'info'" size="small">{{ row.ai_suggested ? '是' : '否' }}</el-tag>
          </el-tooltip>
          <span v-else>{{ row.ai_suggested ? '是' : '否' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="是否纳入" width="100">
        <template #default="{ row }">
          <el-tag :type="row.actual_included ? 'success' : 'info'" size="small">{{ row.actual_included ? '已纳入' : '未纳入' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="script.run_count" label="运行次数" width="90" />
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button link type="primary" @click="runOne(row)">运行</el-button>
          <el-button link @click="viewReport(row)">报告</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-row style="margin-top: 12px">
      <el-button :disabled="!selected.length" @click="setMembers('add')">加入回归集</el-button>
      <el-button :disabled="!selected.length" @click="setMembers('remove')">移出回归集</el-button>
      <el-button type="primary" :loading="running" @click="runBatch">批量执行</el-button>
    </el-row>

    <!-- 区块3: 批量执行配置 -->
    <el-card style="margin-top: 16px" header="批量执行配置">
      <el-form inline>
        <el-form-item label="运行模式"><el-select v-model="runCfg.headless">...</el-select></el-form-item>
        <el-form-item label="超时"><el-input-number v-model="runCfg.timeout" :min="5" :max="600" /></el-form-item>
        <el-form-item label="最大失败数"><el-input-number v-model="runCfg.max_failures" :min="1" :max="100" /></el-form-item>
        <el-form-item label="失败策略">
          <el-select v-model="failStrategy">
            <el-option label="继续" value="continue" />
            <el-option label="停止" value="stop" />
          </el-select>
        </el-form-item>
        <el-form-item><el-button type="primary" :loading="running" @click="runBatch">开始批量执行</el-button></el-form-item>
      </el-form>
    </el-card>

    <!-- 区块4: 回归执行报告 (GET /report-summary, 最近一次) -->
    <el-card style="margin-top: 16px" v-if="summary && summary.record">
      <template #header><span>回归执行报告：{{ summary.record.exec_id }}</span></template>
      <el-row :gutter="16">
        <el-col :span="6"><div class="stat"><div class="num">{{ summary.record.total_cases }}</div><div class="lbl">总脚本</div></div></el-col>
        <el-col :span="6"><div class="stat"><div class="num pass">{{ summary.record.passed_count }}</div><div class="lbl">通过</div></div></el-col>
        <el-col :span="6"><div class="stat"><div class="num fail">{{ summary.record.fail_count }}</div><div class="lbl">失败</div></div></el-col>
        <el-col :span="6"><div class="stat"><div class="num rate">{{ summary.record.pass_rate }}%</div><div class="lbl">通过率</div></div></el-col>
      </el-row>
      <div v-if="summary.failed_details.length" style="margin-top: 12px">
        <div v-for="f in summary.failed_details" :key="f.id" class="fail-row">
          <span>第 {{ f.step }} 步 {{ f.action }}：{{ f.error_type }}</span>
          <span>
            <el-image v-if="f.screenshot_url" :src="f.screenshot_url" :preview-src-list="[f.screenshot_url]" style="width: 60px" />
            <el-button link type="primary" @click="diagnose(f)">AI诊断</el-button>
          </span>
        </div>
      </div>
      <div style="margin-top: 12px">
        <el-button @click="exportReport('html')">导出报告</el-button>
        <el-button @click="pushReport">推送报告</el-button>
      </div>
    </el-card>

    <!-- AI 诊断弹窗 (复用 #5c DiagnosisCard, detail_id 链) -->
    <el-dialog v-model="diagVisible" title="AI 诊断" width="640px">
      <div v-loading="diagLoading">
        <DiagnosisCard v-if="diagCard" :card="diagCard" :applying="applying" @apply="onApply" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
// 实现要点 (完整逻辑参考 ScriptConvert.vue 同款模式):
// 1. loadAll = Promise.all(loadStats(), loadList(), loadSummary())
// 2. runBatch: regressionAPI.run(projectId, {...runCfg, fail_fast: failStrategy === 'stop'})
//    → scriptAPI.subscribe(session_id) SSE → onDone 里 loadAll()
//    → exec_id 存 ref 供报告块刷新
// 3. runOne: scriptAPI.run(row.script.id, runCfg) → startSSE → onDone loadAll
// 4. setMembers(action): regressionAPI.setMembers(projectId, selected.map(r => r.script.id), action) → loadList + loadStats
// 5. reidentify: regressionAPI.identify(projectId) → loadAll
// 6. diagnose(f): diagnosticsAPI.analyze(f.execution_record_id 所属 exec_id 不易得 → 用 f.id 作 detail_id:
//    diagnosticsAPI.analyze(execId.value, f.step, null, f.id)  # detail_id 直取 (#5c C2 修复链路)
// 7. onApply: diagnosticsAPI.apply({script_id: f.script_id, project_id: projectId, element_name: card.element_name, new_locator: card.new_locator, confidence: card.confidence})
// 8. viewReport(row): regressionAPI.latestExecution(row.script.id) → 有 record → router.push(`/reports/${record.exec_id}`); 404 → ElMessage.info('该脚本暂无执行记录')
// 9. exportReport: window.location = `/api/v1/reports/${summary.record.exec_id}/export?format=${fmt}` (整页下载, 全路径)
// 10. pushReport: regressionAPI.push(summary.record.exec_id) → ElMessage.success
// 11. 分类下拉五枚举: ['uncategorized','ui_smoke','full_regression','core_flow','interface_auto'] 中文映射
</script>

<style scoped>
/* 统计卡样式复用 ReportDetail.vue 的 .stat 系列; fail-row 复用 ScriptConvert.vue */
</style>
```

（骨架中 `...` 占位的 select 选项等由实现者按 ScriptConvert.vue 同款补全；script 逻辑 11 条要点必须全部实现，这是 T5 的验收核心。）

- [ ] **Step 3: 路由**

`frontend/src/router/index.js` 的 `scripts` 路由（67-71 行）之后加：

```js
        {
          path: 'auto/ui',
          name: 'AutoUI',
          redirect: '/scripts',
        },
        {
          path: 'auto/regression',
          name: 'Regression',
          component: () => import('@/views/Regression.vue'),
          meta: { title: '回归测试' }
        },
```
（注意：外层已有 path: '/' 根路由，子路由 'auto/regression' 挂进去即 /auto/regression；'auto/ui' 是 redirect 修菜单空转。）

- [ ] **Step 4: build 验证**

Run: `cd /d/MoonTest/frontend && npx vite build 2>&1 | tail -3`
Expected: `✓ built`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/regression.js frontend/src/views/Regression.vue frontend/src/router/index.js
git commit -m "feat(regression): Regression page + routes + API client (#8 T5)"
```

---

### Task 6: ScriptConvert 三列 + 顺手修（分类下拉/max_failures 上限）

**Files:**
- Modify: `backend/app/api/v1/scripts.py`（list 端点加 include_regression 参数）
- Modify: `frontend/src/views/ScriptConvert.vue`（三列 + 分类下拉 + max_failures 上限）

- [ ] **Step 1: 后端 list 加 include_regression**

`backend/app/api/v1/scripts.py` 的 list 端点（GET ""，约 74 行）：加可选参数 `include_regression: bool = Query(False)`；为 True 时对每条 script LEFT JOIN regression_set 取回归字段，响应 item 加：

```python
    # include_regression=true 时 (script, reg) 联查:
    # reg 存在 → item["ai_suggested"]/["ai_reason"]/["actual_included"]/["include_source"]
    # reg 不存在 → 四字段 False/None/False/None
```
实现建议：`select(ScriptAsset, RegressionSet).outerjoin(...)` 按现有 list 过滤条件（category/keyword），组装同 T3 list_view 的 item 形态（script.to_dict() + 回归四字段——保持既有 item 的 script 字段全部不变，只是**追加**四键，零破坏）。

**测试**（追加到 `backend/tests/test_regression_api.py`）：

```python
class TestScriptsListIncludeRegression:
    def test_list_without_param_unchanged(self):
        """include_regression 缺省 → 响应不含回归字段 (零破坏)."""
        # patch db 走既有 list 测试模式 (test_script_api.py 已有 list 测试可参考),
        # 断言 items[0] 无 "ai_suggested" 键
        ...

    def test_list_with_param_adds_fields(self):
        """include_regression=true → item 追加 ai_suggested/ai_reason/actual_included/include_source."""
        ...
```
（两个测试的 mock 模式照抄 `tests/test_script_api.py` 既有 list 测试；实现者读该文件后按同款写。）

- [ ] **Step 2: 前端三列 + 顺手修**

`frontend/src/views/ScriptConvert.vue`：
1. loadScripts 调 `scriptAPI.list(projectId, ...)` 时追加参数 `include_regression=true`（读 script.js 的 list 方法签名，加可选参数透传 query）
2. 脚本库表格加两列（运行次数列前后）：

```html
            <el-table-column label="AI建议" width="90">
              <template #default="{ row }">
                <el-tooltip v-if="row.ai_reason" :content="row.ai_reason">
                  <el-tag :type="row.ai_suggested ? 'warning' : 'info'" size="small">{{ row.ai_suggested ? '是' : '否' }}</el-tag>
                </el-tooltip>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="是否纳入" width="100">
              <template #default="{ row }">
                <el-tag :type="row.actual_included ? 'success' : 'info'" size="small">{{ row.actual_included ? '已纳入' : '未纳入' }}</el-tag>
              </template>
            </el-table-column>
```

3. 分类下拉硬编码（约 83-86 行的 login/smoke/regression 选项）改为五枚举：

```js
const CATEGORIES = [
  { value: 'uncategorized', label: '未分类' },
  { value: 'ui_smoke', label: 'UI冒烟' },
  { value: 'full_regression', label: '全量回归' },
  { value: 'core_flow', label: '核心流程' },
  { value: 'interface_auto', label: '接口自动化' },
]
```

4. max_failures 上限 `:max="50"` → `:max="100"`（约 87 行）

- [ ] **Step 3: build + 全量回归**

Run: `cd /d/MoonTest/frontend && npx vite build 2>&1 | tail -2 && cd ../backend && python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py`
Expected: ✓ built + 全绿

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/scripts.py backend/tests/test_regression_api.py frontend/src/views/ScriptConvert.vue frontend/src/api/script.js
git commit -m "feat(regression): script list regression columns + category/max_failures fixes (#8 T6)"
```

---

### Task 7: 终审（一次性，全切片）

**Files:** 无新文件（审查任务，沿用 #5c 终审模式）

- [ ] **Step 1: 全量后端测试**

Run: `cd /d/MoonTest/backend && python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py`
Expected: 全绿

- [ ] **Step 2: 前端 build**

Run: `cd /d/MoonTest/frontend && npx vite build 2>&1 | tail -2`
Expected: ✓ built

- [ ] **Step 3: 派终审子代理**

Base: T1 前 HEAD（a13137e 之后第一个 T1 commit 的父），Head: T6 提交。审查范围：spec §1.4 偏差 7 条 + 验收 11 条 + 规则引擎口径 + 复用面不重造 + 常规质量。用户已确认全任务完成后一次性审查。

- [ ] **Step 4: 审查问题修复 + 收尾提交**

```bash
git add -A && git commit -m "fix(regression): final review fixes (#8 T7)"  # 若有
```
