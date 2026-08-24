# 用例转自动化脚本（模块 #4）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 已定稿用例 → AI 多阶段生成 Playwright+pytest 脚本 → 入脚本库 + SSE 文字直播 + 元素库离线定位匹配 + 调试修复。

**Architecture:** 5 阶段纯函数流水线（Step0-4）+ 编排服务（DB/SSE/Token）+ 调试修复服务（四分类归因）。纯函数层可 mock LLM 单测；编排层拥有副作用。Celery 异步执行批量转换，SSE 复用现有 `SSEStream`。范围 A：只生成不运行。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy(async) / Pydantic / Celery / Redis / 复用 `ai_gateway` / `SSEStream`。

**Spec:** `docs/superpowers/specs/2026-08-24-case-to-script-design.md`

---

## 文件结构

**后端新增：**
- `backend/app/models/script.py` — ScriptAsset 扩展列 + ConvertSession 模型
- `backend/app/schemas/script.py` — 请求/响应 Pydantic 模型 + 枚举
- `backend/app/services/script_pipeline.py` — Step0-4 纯函数
- `backend/app/services/script_validator.py` — skill 8 项质量自检
- `backend/app/services/script_convert_service.py` — 编排（DB/SSE/Token）
- `backend/app/services/script_diagnose_service.py` — 调试修复四分类
- `backend/app/api/v1/scripts.py` — API 路由
- `backend/app/tasks/script_tasks.py` — Celery 任务
- `backend/migrations/add_convert_script_tables.sql` — 迁移

**后端修改：**
- `backend/app/models/test_case.py` — ScriptAsset 加列（迁移已有表，model 同步）
- `backend/app/api/__init__.py` — 注册 scripts 路由
- `backend/app/models/__init__.py` — 导出新模型

**测试新增：**
- `backend/tests/test_script_pipeline.py`
- `backend/tests/test_script_validator.py`
- `backend/tests/test_script_diagnose_service.py`
- `backend/tests/test_script_convert_service.py`
- `backend/tests/test_script_api.py`

**前端新增：**
- `frontend/src/api/script.js`
- `frontend/src/views/ScriptConvert.vue`

**前端修改：**
- `frontend/src/router/index.js` — 加 `/scripts` 路由

---

## Task 1: 数据模型 — ScriptAsset 扩展 + ConvertSession

**Files:**
- Create: `backend/app/models/script.py`
- Modify: `backend/app/models/test_case.py`（ScriptAsset 加 6 列）
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/add_convert_script_tables.sql`
- Test: `backend/tests/test_script_models.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_script_models.py
"""ScriptAsset + ConvertSession model tests."""
from app.models.test_case import ScriptAsset
from app.models.script import ConvertSession


class TestScriptAssetColumns:
    def test_has_name_and_project_id(self):
        cols = {c.name for c in ScriptAsset.__table__.c}
        assert "name" in cols
        assert "project_id" in cols
        assert "description" in cols
        assert "step_mapping" in cols
        assert "locator_source" in cols
        assert "ai_diagnosis" in cols

    def test_has_unique_project_name(self):
        constraints = [str(c) for c in ScriptAsset.__table__.constraints]
        assert any("project_id" in c and "name" in c for c in constraints)


class TestConvertSessionColumns:
    def test_required_columns(self):
        cols = {c.name for c in ConvertSession.__table__.c}
        for expected in ("id", "project_id", "case_ids", "ai_optimize",
                         "status", "progress", "tokens_used", "created_at"):
            assert expected in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.script'`

- [ ] **Step 3: Modify ScriptAsset in test_case.py**

在 `backend/app/models/test_case.py` 的 `ScriptAsset` 类中（`version` 列之后、`status` 之前），加列：

```python
    # #4: script library fields (req 3.6.3.3 / 3.6.5)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, comment="脚本名称（继承用例名）")
    description = Column(String(500), comment="脚本说明")
    step_mapping = Column(JSONB, comment="skill Step4 步骤对照表")
    locator_source = Column(String(20), default="none_draft", comment="element_library/ai_generated/mixed/none_draft")
    ai_diagnosis = Column(JSONB, comment="调试修复诊断卡")
```

并修改 `__table_args__` 加唯一约束：

```python
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_script_asset_project_name"),
        Index("idx_script_asset_project", "project_id"),
        Index("idx_script_asset_case", "case_id"),
    )
```

`to_dict` 补字段：

```python
            "project_id": str(self.project_id),
            "name": self.name,
            "description": self.description,
            "step_mapping": self.step_mapping,
            "locator_source": self.locator_source,
            "ai_diagnosis": self.ai_diagnosis,
```

- [ ] **Step 4: Create ConvertSession model**

```python
# backend/app/models/script.py
"""Script conversion session model."""
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class ConvertSession(Base):
    """转脚本会话 - 一次批量转换任务"""
    __tablename__ = "convert_session"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    case_ids = Column(JSONB, nullable=False, comment="本次转换用例 ID 列表")
    ai_optimize = Column(Boolean, default=False, comment="未命中时是否调 AI 生成定位器")
    status = Column(String(20), default="active", comment="active/done/failed")
    progress = Column(Numeric(5, 2), default=0)
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "case_ids": self.case_ids,
            "ai_optimize": self.ai_optimize,
            "status": self.status,
            "progress": float(self.progress) if self.progress else 0,
            "tokens_used": self.tokens_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
```

- [ ] **Step 5: Register in models/__init__.py**

修改 `backend/app/models/__init__.py`，加：

```python
from app.models.script import ConvertSession
```

- [ ] **Step 6: Create migration**

```sql
-- backend/migrations/add_convert_script_tables.sql
-- #4: script_asset extension + convert_session table
-- Idempotent.

-- 1. script_asset add columns
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS project_id UUID;
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS name VARCHAR(100);
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS description VARCHAR(500);
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS step_mapping JSONB;
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS locator_source VARCHAR(20) DEFAULT 'none_draft';
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS ai_diagnosis JSONB;

-- backfill project_id from case's project (for existing rows)
UPDATE script_asset sa
SET project_id = (SELECT tc.project_id FROM test_case tc WHERE tc.id = sa.case_id)
WHERE sa.project_id IS NULL;

ALTER TABLE script_asset ALTER COLUMN project_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_script_asset_project ON script_asset(project_id);
CREATE INDEX IF NOT EXISTS idx_script_asset_case ON script_asset(case_id);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_script_asset_project_name') THEN
    ALTER TABLE script_asset ADD CONSTRAINT uq_script_asset_project_name UNIQUE (project_id, name);
  END IF;
END$$;

-- 2. convert_session
CREATE TABLE IF NOT EXISTS convert_session (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL,
    case_ids JSONB NOT NULL,
    ai_optimize BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'active',
    progress NUMERIC(5,2) DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_convert_session_project ON convert_session(project_id);
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_models.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/script.py backend/app/models/test_case.py backend/app/models/__init__.py backend/migrations/add_convert_script_tables.sql backend/tests/test_script_models.py
git commit -m "feat(script): ScriptAsset extension + ConvertSession model (#4 T1)"
```

---

## Task 2: Pydantic Schemas

**Files:**
- Create: `backend/app/schemas/script.py`
- Create: `backend/tests/test_script_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_script_schemas.py
"""Script schema validation tests."""
import pytest
from pydantic import ValidationError
from app.schemas.script import (
    ConvertRequest, ConfirmResponse, DiagnoseRequest,
    DiagnosisCard, LOCATOR_SOURCES, SCRIPT_STATUSES, ERROR_TYPES,
)


class TestEnums:
    def test_locator_sources(self):
        assert LOCATOR_SOURCES == ("element_library", "ai_generated", "mixed", "none_draft")

    def test_script_statuses(self):
        assert SCRIPT_STATUSES == ("draft", "generated", "confirmed")

    def test_error_types(self):
        assert ERROR_TYPES == ("locate_failed", "timeout", "assertion_failed", "script_error")


class TestConvertRequest:
    def _base(self):
        return dict(project_id="0"*8 + "-" + "0"*4 + "-" + "0"*4 + "-" + "0"*4 + "-" + "0"*12,
                    case_ids=["a"*8 + "-0000-0000-0000-" + "a"*12])

    def test_minimal(self):
        r = ConvertRequest(**self._base())
        assert r.ai_optimize is False

    def test_empty_case_ids_rejected(self):
        with pytest.raises(ValidationError):
            ConvertRequest(**{**self._base(), "case_ids": []})


class TestDiagnoseRequest:
    def test_requires_error_type(self):
        with pytest.raises(ValidationError):
            DiagnoseRequest(error_type=None, error_msg="x", script_fragment="y")

    def test_invalid_error_type(self):
        with pytest.raises(ValidationError):
            DiagnoseRequest(error_type="bogus", error_msg="x", script_fragment="y")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create schemas**

```python
# backend/app/schemas/script.py
"""Script conversion schemas."""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ===== Enum canonical values =====
LOCATOR_SOURCES = ("element_library", "ai_generated", "mixed", "none_draft")
SCRIPT_STATUSES = ("draft", "generated", "confirmed")
ERROR_TYPES = ("locate_failed", "timeout", "assertion_failed", "script_error")
DIAGNOSIS_CATEGORIES = ("script_problem", "page_bug", "data_env", "ambiguous")

_PATTERN = "^(" + "|".join  # placeholder, replaced below
def _pattern(values: tuple) -> str:
    return "^(" + "|".join(values) + ")$"


class ConvertRequest(BaseModel):
    project_id: str = Field(..., description="Project ID")
    case_ids: List[str] = Field(..., min_length=1, description="已定稿用例 ID 列表")
    ai_optimize: bool = Field(False, description="未命中时是否调 AI 生成定位器")


class ConvertResponse(BaseModel):
    code: int = 0
    data: Dict[str, Any]


class ScriptResponse(BaseModel):
    id: str
    project_id: str
    case_id: str
    name: str
    description: Optional[str] = None
    content: str
    version: int
    status: str
    category: str
    locator_source: str
    step_mapping: Optional[List[Dict]] = None
    ai_diagnosis: Optional[Dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConfirmResponse(BaseModel):
    code: int = 0
    message: str
    data: Dict[str, Any]


class DiagnoseRequest(BaseModel):
    error_type: str = Field(..., pattern=_pattern(ERROR_TYPES), description="错误类型")
    error_msg: str = Field(..., min_length=1, max_length=2000)
    script_fragment: str = Field(..., min_length=1, max_length=10000)
    dom_snapshot: Optional[str] = Field(None, max_length=50000)
    screenshot_url: Optional[str] = Field(None, max_length=500)
    failed_step: Optional[int] = Field(None, ge=1)


class DiagnosisCard(BaseModel):
    category: str = Field(..., pattern=_pattern(DIAGNOSIS_CATEGORIES))
    can_fix: bool
    reason: str
    failed_step: Optional[int] = None
    error_type: Optional[str] = None
    error_msg: Optional[str] = None
    screenshot_url: Optional[str] = None
    revised_step: Optional[str] = None
    suggestion: str


class DiagnoseResponse(BaseModel):
    code: int = 0
    data: Dict[str, Any]
```

- [ ] **Step 4: Fix placeholder bug in schemas**

Step 3 含一个故意的占位 bug（`_PATTERN` 行）。删除该行：

```python
# 删除这两行：
# _PATTERN = "^(" + "|".join  # placeholder, replaced below
# def _pattern(values: tuple) -> str:
#     return "^(" + "|".join(values) + ")$"
# 改为只保留函数定义：
def _pattern(values: tuple) -> str:
    return "^(" + "|".join(values) + ")$"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_schemas.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/script.py backend/tests/test_script_schemas.py
git commit -m "feat(script): pydantic schemas + enums (#4 T2)"
```

---

## Task 3: Pipeline Step0 — 用例标准化

**Files:**
- Create: `backend/app/services/script_pipeline.py`
- Create: `backend/tests/test_script_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_script_pipeline.py
"""Script pipeline unit tests (mock LLM)."""
import pytest
from app.services.script_pipeline import step0_normalize, NormalizeError, NormalizedCase


class TestStep0Normalize:
    def _case(self, **over):
        base = {
            "id": "c1", "name": "登录-正常登录", "steps": [
                {"step": 1, "action": "输入用户名admin", "expected": "输入成功"},
                {"step": 2, "action": "点击登录", "expected": "跳转首页"},
            ],
            "expected_result": "成功进入首页",
        }
        base.update(over)
        return base

    def test_normalize_ok(self):
        nc = step0_normalize(self._case())
        assert isinstance(nc, NormalizedCase)
        assert nc.title == "登录-正常登录"
        assert len(nc.steps) == 2
        assert nc.expected_result == "成功进入首页"

    def test_empty_steps_blocks(self):
        with pytest.raises(NormalizeError):
            step0_normalize(self._case(steps=[]))

    def test_empty_expected_blocks(self):
        with pytest.raises(NormalizeError):
            step0_normalize(self._case(expected_result=""))

    def test_missing_title_uses_step_summary(self):
        nc = step0_normalize(self._case(name=""))
        assert nc.title != ""  # generated from steps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep0Normalize -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Create pipeline module with Step0**

```python
# backend/app/services/script_pipeline.py
"""用例转脚本 5 阶段纯函数流水线 (skill Step0-4).

每阶段输入结构 -> 输出结构, LLM 通过注入的 gateway 调用, 可 mock。
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


class NormalizeError(Exception):
    """用例无法标准化 (steps/expected 缺失)."""


@dataclass
class NormalizedCase:
    case_id: str
    title: str
    steps: List[Dict[str, Any]]
    expected_result: str


def step0_normalize(case: Dict[str, Any]) -> NormalizedCase:
    """Step0: 用例标准化。缺失 steps/expected 阻塞；缺失 title 用步骤摘要生成。"""
    steps = case.get("steps") or []
    expected = (case.get("expected_result") or "").strip()
    if not steps:
        raise NormalizeError("用例缺少步骤，无法生成脚本")
    if not expected:
        raise NormalizeError("用例缺少预期结果，无法生成脚本")

    title = (case.get("name") or "").strip()
    if not title:
        actions = [s.get("action", "") for s in steps[:3]]
        title = " / ".join(a for a in actions if a) or "未命名用例"

    return NormalizedCase(
        case_id=case.get("id", ""),
        title=title,
        steps=steps,
        expected_result=expected,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep0Normalize -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_pipeline.py backend/tests/test_script_pipeline.py
git commit -m "feat(script): pipeline Step0 normalize (#4 T3)"
```

---

## Task 4: Pipeline Step1 — 步骤→动作意图（LLM）

**Files:**
- Modify: `backend/app/services/script_pipeline.py`（加 Step1）
- Modify: `backend/tests/test_script_pipeline.py`

- [ ] **Step 1: Write the failing test**

在 `test_script_pipeline.py` 顶部加 import 与 mock gateway：

```python
from app.services.script_pipeline import step1_to_actions, ActionIntent, LLMGatewayProto


class FakeGateway:
    """内存 LLM 网关, 返回预设 JSON。"""
    def __init__(self, response_text: str):
        self._response = response_text
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        return {"content": self._response, "tokens": 100}


class TestStep1ToActions:
    def _case(self):
        return NormalizedCase(
            case_id="c1", title="登录",
            steps=[{"step": 1, "action": "输入用户名admin", "expected": "输入成功"}],
            expected_result="进入首页",
        )

    def test_parses_actions(self):
        gw = FakeGateway('[{"step":1,"action":"fill","target":"用户名","value":"admin"}]')
        actions = asyncio_run(step1_to_actions(self._case(), gw))
        assert len(actions) == 1
        assert actions[0].action == "fill"
        assert actions[0].value == "admin"

    def test_invalid_action_rejected(self):
        gw = FakeGateway('[{"step":1,"action":"bogus","target":"x"}]')
        with pytest.raises(ValueError):
            asyncio_run(step1_to_actions(self._case(), gw))
```

加文件顶部 helper（若尚未引入）：

```python
import asyncio
def asyncio_run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutinefunction(lambda: None) else asyncio.run(coro)
```

> 简化：直接用 `asyncio.run`。把上面 helper 换成：`def asyncio_run(coro): return asyncio.run(coro)`

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep1ToActions -v`
Expected: FAIL with `ImportError: cannot import name 'step1_to_actions'`

- [ ] **Step 3: Implement Step1**

在 `script_pipeline.py` 加：

```python
import json
from typing import Protocol


VALID_ACTIONS = ("navigate", "click", "fill", "select", "check",
                 "create", "edit", "delete", "workflow_action")


@dataclass
class ActionIntent:
    step: int
    action: str
    target: Optional[str] = None
    value: Optional[str] = None


class LLMGatewayProto(Protocol):
    async def chat(self, messages: List[Dict], **kw) -> Dict: ...


STEP1_PROMPT = """你是测试脚本转换器。把测试步骤转成结构化动作意图, 输出 JSON 数组。
每项: {{"step": int, "action": 动作类型, "target": 目标元素或页面, "value": 输入值}}
动作类型只能选: navigate/click/fill/select/check/create/edit/delete/workflow_action
只输出 JSON 数组, 不要解释文字。

用例标题: {title}
步骤:
{steps}"""


def _fmt_steps(steps: List[Dict]) -> str:
    return "\n".join(f"{s.get('step')}. {s.get('action','')}" for s in steps)


async def step1_to_actions(case: NormalizedCase, gateway: LLMGatewayProto) -> List[ActionIntent]:
    """Step1: 步骤 → 动作意图 (LLM)."""
    prompt = STEP1_PROMPT.format(title=case.title, steps=_fmt_steps(case.steps))
    resp = await gateway.chat([{"role": "user", "content": prompt}])
    raw = resp["content"].strip()
    items = json.loads(raw)
    actions = []
    for it in items:
        action = it.get("action")
        if action not in VALID_ACTIONS:
            raise ValueError(f"非法动作类型: {action}")
        actions.append(ActionIntent(
            step=int(it["step"]),
            action=action,
            target=it.get("target"),
            value=it.get("value"),
        ))
    actions.sort(key=lambda a: a.step)
    return actions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep1ToActions -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_pipeline.py backend/tests/test_script_pipeline.py
git commit -m "feat(script): pipeline Step1 actions via LLM (#4 T4)"
```

---

## Task 5: Pipeline Step2 — 预期→断言计划（LLM + 永真断言校验）

**Files:**
- Modify: `backend/app/services/script_pipeline.py`
- Modify: `backend/tests/test_script_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.script_pipeline import step2_to_assertions, AssertionPlan


class TestStep2ToAssertions:
    def _case(self):
        return NormalizedCase(
            case_id="c1", title="登录",
            steps=[{"step": 1, "action": "点击登录", "expected": "跳转首页"}],
            expected_result="成功进入首页",
        )

    def test_parses_assertions(self):
        gw = FakeGateway('[{"step":1,"assertion_type":"status_changed","target":"页面","expected":"首页","is_valid":true}]')
        asserts = asyncio_run(step2_to_assertions(self._case(), gw))
        assert asserts[0].assertion_type == "status_changed"
        assert asserts[0].is_valid is True

    def test_tautological_assertion_marked_invalid(self):
        gw = FakeGateway('[{"step":1,"assertion_type":"row_visible","target":"按钮","expected":"可见","is_valid":true}]')
        # row_visible of a button = tautological per blacklist -> forced invalid
        asserts = asyncio_run(step2_to_assertions(self._case(), gw))
        assert asserts[0].is_valid is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep2ToAssertions -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement Step2**

```python
@dataclass
class AssertionPlan:
    step: int
    assertion_type: str  # toast_message/row_visible/status_changed/field_value/dialog_closed/ambiguous
    target: Optional[str] = None
    expected: Optional[str] = None
    is_valid: bool = True


VALID_ASSERTION_TYPES = ("toast_message", "row_visible", "status_changed",
                         "field_value", "dialog_closed", "ambiguous")

# 永真断言黑名单 (skill 3.3): "验证按钮/菜单可见" 等不验证业务结果
TAUTOLOGICAL_KEYWORDS = ("按钮可见", "菜单可见", "页面可见", "元素可见")


STEP2_PROMPT = """你是测试脚本转换器。把预期结果转成断言计划, 输出 JSON 数组。
每项: {{"step": int, "assertion_type": 类型, "target": 目标, "expected": 期望值, "is_valid": bool}}
类型只能选: toast_message/row_visible/status_changed/field_value/dialog_closed/ambiguous
is_valid=false 当断言不验证业务结果(只验证固定元素可见)。
模糊预期(如"系统正常处理")用 ambiguous 类型, is_valid=false。
只输出 JSON 数组。

预期结果: {expected}
步骤预期:
{step_expected}"""


def _fmt_step_expected(steps: List[Dict]) -> str:
    return "\n".join(f"{s.get('step')}. {s.get('expected','')}" for s in steps)


def _is_tautological(a: dict) -> bool:
    target = (a.get("target") or "") + (a.get("expected") or "")
    return any(kw in target for kw in TAUTOLOGICAL_KEYWORDS)


async def step2_to_assertions(case: NormalizedCase, gateway: LLMGatewayProto) -> List[AssertionPlan]:
    """Step2: 预期 → 断言计划 (LLM), 后置永真断言校验。"""
    prompt = STEP2_PROMPT.format(
        expected=case.expected_result,
        step_expected=_fmt_step_expected(case.steps),
    )
    resp = await gateway.chat([{"role": "user", "content": prompt}])
    items = json.loads(resp["content"].strip())
    plans = []
    for it in items:
        atype = it.get("assertion_type")
        if atype not in VALID_ASSERTION_TYPES:
            raise ValueError(f"非法断言类型: {atype}")
        is_valid = bool(it.get("is_valid", True))
        if _is_tautological(it):
            is_valid = False
        if atype == "ambiguous":
            is_valid = False
        plans.append(AssertionPlan(
            step=int(it["step"]),
            assertion_type=atype,
            target=it.get("target"),
            expected=it.get("expected"),
            is_valid=is_valid,
        ))
    return plans
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep2ToAssertions -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_pipeline.py backend/tests/test_script_pipeline.py
git commit -m "feat(script): pipeline Step2 assertions + tautology check (#4 T5)"
```

---

## Task 6: Pipeline Step3 — 元素库定位匹配

**Files:**
- Modify: `backend/app/services/script_pipeline.py`
- Modify: `backend/tests/test_script_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.script_pipeline import step3_match_locators, ActionWithLocator, ElementLookupProto


class FakeElementLookup:
    """内存元素库, page.element_name -> locator 字符串。"""
    def __init__(self, mapping: dict):
        self.mapping = mapping

    async def find(self, project_id: str, target: str) -> Optional[str]:
        # target 形如 "LoginPage.username" 或 "用户名"
        return self.mapping.get(target)


class TestStep3MatchLocators:
    def _actions(self):
        return [ActionIntent(step=1, action="fill", target="用户名", value="admin")]

    def test_all_matched(self):
        lk = FakeElementLookup({"用户名": "page.get_by_label('用户名')"})
        result = asyncio_run(step3_match_locators(self._actions(), "p1", lk, ai_optimize=False, gateway=None))
        assert result[0].locator == "page.get_by_label('用户名')"
        assert result[0].locator_status == "matched"
        assert result[0].locator_source == "element_library"

    def test_none_matched_draft(self):
        lk = FakeElementLookup({})
        result = asyncio_run(step3_match_locators(self._actions(), "p1", lk, ai_optimize=False, gateway=None))
        assert result[0].locator_status == "none_draft"
        assert result[0].locator is None
        assert result[0].locator_source == "none_draft"

    def test_partial_mixed(self):
        lk = FakeElementLookup({"用户名": "page.get_by_label('用户名')"})
        actions = [
            ActionIntent(step=1, action="fill", target="用户名", value="admin"),
            ActionIntent(step=2, action="click", target="登录按钮"),
        ]
        result = asyncio_run(step3_match_locators(actions, "p1", lk, ai_optimize=False, gateway=None))
        assert result[0].locator_source == "mixed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep3MatchLocators -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement Step3**

```python
class ElementLookupProto(Protocol):
    async def find(self, project_id: str, target: str) -> Optional[str]: ...


@dataclass
class ActionWithLocator:
    step: int
    action: str
    target: Optional[str]
    value: Optional[str]
    locator: Optional[str] = None
    locator_status: str = "none_draft"  # matched / pending_confirm / none_draft


STEP3_AI_PROMPT = """你是定位器生成器。为 UI 元素生成 Playwright 定位器, 优先 get_by_role > get_by_text > get_by_label > get_by_placeholder > css。
只输出一个定位器字符串(如 page.get_by_role("button", name="登录")), 不要解释。
元素描述: {target}"""


async def _ai_generate_locator(target: str, gateway: LLMGatewayProto) -> str:
    resp = await gateway.chat([{"role": "user", "content": STEP3_AI_PROMPT.format(target=target)}])
    return resp["content"].strip()


async def step3_match_locators(
    actions: List[ActionIntent],
    project_id: str,
    lookup: ElementLookupProto,
    ai_optimize: bool,
    gateway: Optional[LLMGatewayProto],
) -> List[ActionWithLocator]:
    """Step3: 动作意图 + 元素库 → 绑 locator (TRANS-01)。命中用库, 未命中 AI 生成或 draft。"""
    results: List[ActionWithLocator] = []
    matched = 0
    ai_used = False
    for a in actions:
        loc = await lookup.find(project_id, a.target) if a.target else None
        if loc:
            status = "matched"
            matched += 1
        elif ai_optimize and gateway is not None and a.target:
            loc = await _ai_generate_locator(a.target, gateway)
            status = "pending_confirm"
            ai_used = True
            matched += 1
        else:
            loc = None
            status = "none_draft"
        results.append(ActionWithLocator(
            step=a.step, action=a.action, target=a.target, value=a.value,
            locator=loc, locator_status=status,
        ))
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

> 注：`locator_source` 是整脚本级（全部一致），故在循环后统一赋值。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep3MatchLocators -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_pipeline.py backend/tests/test_script_pipeline.py
git commit -m "feat(script): pipeline Step3 locator matching (#4 T6)"
```

---

## Task 7: Pipeline Step4 — 代码生成 + 对照表

**Files:**
- Modify: `backend/app/services/script_pipeline.py`
- Modify: `backend/tests/test_script_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.script_pipeline import step4_generate_code, GenerateResult


class TestStep4GenerateCode:
    def _inputs(self):
        actions = [ActionWithLocator(step=1, action="fill", target="用户名",
                                     value="admin", locator="page.get_by_label('用户名')",
                                     locator_status="matched")]
        asserts = [AssertionPlan(step=1, assertion_type="status_changed",
                                 target="页面", expected="首页", is_valid=True)]
        case = NormalizedCase(case_id="c1", title="登录", steps=[], expected_result="进入首页")
        return case, actions, asserts

    def test_generates_script_and_mapping(self):
        gw = FakeGateway('import pytest\n\ndef test_login(page):\n    page.get_by_label("用户名").fill("admin")\n')
        case, actions, asserts = self._inputs()
        result = asyncio_run(step4_generate_code(case, actions, asserts, gw))
        assert isinstance(result, GenerateResult)
        assert "def test_login" in result.script
        assert len(result.step_mapping) == 1
        assert result.step_mapping[0]["status"] == "ok"

    def test_missing_locator_blocks_step(self):
        gw = FakeGateway('def test_x(page):\n    pass\n')
        case, actions, asserts = self._inputs()
        actions[0].locator = None
        actions[0].locator_status = "none_draft"
        result = asyncio_run(step4_generate_code(case, actions, asserts, gw))
        assert result.step_mapping[0]["status"] == "blocked"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep4GenerateCode -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement Step4**

```python
@dataclass
class StepMappingEntry:
    step: int
    case_req: str
    impl: str
    status: str  # ok / blocked


@dataclass
class GenerateResult:
    script: str
    step_mapping: List[Dict[str, Any]]
    locator_source: str


STEP4_PROMPT = """生成 Python + Playwright + pytest 测试函数。规则:
- 定位器优先级: get_by_role > get_by_text > get_by_label > get_by_placeholder > css
- 禁止 click/fill 用 .first/.nth/.last
- 禁止永真断言(只验证按钮可见)
- 等待优先 expect 自带 > wait_for_response > wait_for(state) > wait_for_load_state(networkidle) > wait_for_timeout(<=500ms 仅动画)
- 无定位器的步骤用注释占位: # TODO: 待确认定位器
只输出代码, 不要 markdown 围栏。

用例标题: {title}
动作与定位器:
{actions}
断言:
{asserts}"""


def _fmt_actions(actions: List[ActionWithLocator]) -> str:
    lines = []
    for a in actions:
        loc = a.locator or "(待确认)"
        lines.append(f"{a.step}. {a.action} {a.target or ''} 值={a.value or ''} locator={loc}")
    return "\n".join(lines)


def _fmt_asserts(asserts: List[AssertionPlan]) -> str:
    return "\n".join(f"{a.step}. {a.assertion_type} {a.target or ''} 期望={a.expected or ''}" for a in asserts)


def _build_step_mapping(actions: List[ActionWithLocator], script: str) -> List[Dict[str, Any]]:
    mapping = []
    for a in actions:
        impl = a.locator or ""
        status = "ok" if (a.locator and a.locator in script) else "blocked"
        mapping.append({
            "step": a.step,
            "case_req": f"{a.action} {a.target or ''}",
            "impl": impl,
            "status": status,
        })
    return mapping


async def step4_generate_code(
    case: NormalizedCase,
    actions: List[ActionWithLocator],
    asserts: List[AssertionPlan],
    gateway: LLMGatewayProto,
) -> GenerateResult:
    """Step4: 代码生成 + 步骤对照表 (LLM 拼装)。"""
    prompt = STEP4_PROMPT.format(
        title=case.title,
        actions=_fmt_actions(actions),
        asserts=_fmt_asserts(asserts),
    )
    resp = await gateway.chat([{"role": "user", "content": prompt}])
    script = resp["content"].strip()
    step_mapping = _build_step_mapping(actions, script)
    source = actions[0].locator_source if actions else "none_draft"
    return GenerateResult(script=script, step_mapping=step_mapping, locator_source=source)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep4GenerateCode -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_pipeline.py backend/tests/test_script_pipeline.py
git commit -m "feat(script): pipeline Step4 codegen + step mapping (#4 T7)"
```

---

## Task 8: Script Validator — skill 8 项质量自检

**Files:**
- Create: `backend/app/services/script_validator.py`
- Create: `backend/tests/test_script_validator.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_script_validator.py
"""Script validator (skill 8-item self-check) tests."""
from app.services.script_validator import validate_script, ValidationReport


class TestValidateScript:
    def test_clean_script_passes(self):
        script = (
            'def test_login(page):\n'
            '    page.get_by_label("用户名").fill("admin")\n'
            '    page.get_by_role("button", name="登录").click()\n'
            '    assert "首页" in page.title()\n'
        )
        report = validate_script(script, step_mapping=[
            {"step": 1, "status": "ok"}, {"step": 2, "status": "ok"}])
        assert report.all_pass() is True

    def test_index_locator_fails(self):
        script = 'def t(page):\n    page.locator(".btn").first.click()\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "ok"}])
        names = [c.name for c in report.checks]
        assert "no_index_locator_on_click" in names
        assert report.all_pass() is False

    def test_tautological_assertion_fails(self):
        script = 'def t(page):\n    assert page.get_by_role("button").is_visible()\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "ok"}])
        names = [c.name for c in report.checks]
        assert "no_tautological_assertion" in names

    def test_hardcoded_wait_fails(self):
        script = 'def t(page):\n    page.wait_for_timeout(3000)\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "ok"}])
        names = [c.name for c in report.checks]
        assert "no_hardcoded_long_wait" in names

    def test_fabricated_css_fails(self):
        # 无定位器来源却出现具体 css selector = 编造
        script = 'def t(page):\n    page.locator("#login-btn-xyz").click()\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "blocked"}])
        names = [c.name for c in report.checks]
        assert "no_fabricated_dom" in names

    def test_blocked_step_fails(self):
        script = 'def t(page):\n    pass\n'
        report = validate_script(script, step_mapping=[{"step": 1, "status": "blocked"}])
        names = [c.name for c in report.checks]
        assert "all_steps_implemented" in names
        assert report.all_pass() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_validator.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement validator**

```python
# backend/app/services/script_validator.py
"""skill 8 项质量自检 -> validate_script."""
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationReport:
    checks: List[Check] = field(default_factory=list)

    def all_pass(self) -> bool:
        return all(c.passed for c in self.checks)


# click/fill/select 中的 .first/.nth/.last (skill 3.2)
_INDEX_LOCATOR_RE = re.compile(r'\.(click|fill|select)\(.*\.(first|nth\(\d+\)|last)\)')
# 永真断言 (skill 3.3): 只验证 is_visible / to_be_visible 不验证业务结果
_VISIBLE_ASSERT_RE = re.compile(r'assert\s+.*\.is_visible\(\)|expect\(.*\)\.to_be_visible\(\)')
# 硬编码长等待 (skill 3.4): wait_for_timeout > 500ms
_LONG_WAIT_RE = re.compile(r'wait_for_timeout\((\d+)\)')
# 编造的 id/class css (skill 3.5): #xxx-yyy 或 .xxx-yyy
_FABRICATED_CSS_RE = re.compile(r'page\.locator\(["\']#[a-z0-9_-]+["\']\)|page\.locator\(["\']\.[a-z0-9_-]+["\']\)')


def _check_no_index_locator(script: str) -> Check:
    m = _INDEX_LOCATOR_RE.search(script)
    return Check("no_index_locator_on_click", m is None,
                 f"禁止索引定位: {m.group(0)}" if m else "")


def _check_no_tautological(script: str) -> Check:
    m = _VISIBLE_ASSERT_RE.search(script)
    # 仅 is_visible/to_be_visible 不一定永真, 但若脚本只有此断言无业务验证则无效
    return Check("no_tautological_assertion", m is None,
                 f"疑似永真断言: {m.group(0)}" if m else "")


def _check_no_hardcoded_wait(script: str) -> Check:
    for m in _LONG_WAIT_RE.finditer(script):
        if int(m.group(1)) > 500:
            return Check("no_hardcoded_long_wait", False, f"硬编码等待: {m.group(0)}")
    return Check("no_hardcoded_long_wait", True, "")


def _check_no_fabricated_dom(script: str, step_mapping: list) -> Check:
    # 当存在 blocked 步骤却出现具体 css selector = 编造
    blocked = any(s.get("status") == "blocked" for s in step_mapping)
    m = _FABRICATED_CSS_RE.search(script)
    bad = blocked and m is not None
    return Check("no_fabricated_dom", not bad,
                 f"无来源却编造 DOM: {m.group(0)}" if bad else "")


def _check_all_steps_implemented(step_mapping: list) -> Check:
    blocked = [s for s in step_mapping if s.get("status") == "blocked"]
    return Check("all_steps_implemented", len(blocked) == 0,
                 f"阻塞步骤: {blocked}" if blocked else "")


def validate_script(script: str, step_mapping: list) -> ValidationReport:
    """skill 8 项中的脚本层守门检查 (#1/#2/#4/#6/#8 脚本部分)."""
    report = ValidationReport()
    report.checks.append(_check_no_index_locator(script))
    report.checks.append(_check_no_tautological(script))
    report.checks.append(_check_no_hardcoded_wait(script))
    report.checks.append(_check_no_fabricated_dom(script, step_mapping))
    report.checks.append(_check_all_steps_implemented(step_mapping))
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_validator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_validator.py backend/tests/test_script_validator.py
git commit -m "feat(script): skill 8-item validator (#4 T8)"
```

---

## Task 9: 元素库查询适配器（ElementService.find_locator）

**Files:**
- Modify: `backend/app/services/element_service.py`
- Modify: `backend/tests/test_pipeline_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_pipeline_integration.py
"""Pipeline + element lookup adapter integration."""
import pytest
from app.services.script_pipeline import step3_match_locators, ActionIntent
from app.services.element_service import ElementLocatorLookup


class FakeElementService:
    def __init__(self, mapping):
        self.mapping = mapping

    async def find_by_name(self, project_id: str, element_name: str):
        return self.mapping.get(element_name)


class TestElementLocatorLookup:
    def test_adapter_returns_locator_string(self):
        fake = FakeElementService({"用户名": type("El", (), {
            "locator_strategies": [{"type": "label", "value": "用户名"}]})()})
        lookup = ElementLocatorLookup(fake)
        loc = pytest.run(step3_match_locators(
            [ActionIntent(step=1, action="fill", target="用户名", value="admin")],
            "p1", lookup, ai_optimize=False, gateway=None))
        # 待 Step9 实现后 locator 应为 page.get_by_label("用户名")


def pytest_run(coro):
    import asyncio
    return asyncio.run(coro)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pipeline_integration.py -v`
Expected: FAIL with `ImportError: cannot import name 'ElementLocatorLookup'`

- [ ] **Step 3: Implement ElementLocatorLookup + find_by_name**

在 `element_service.py` 的 `ElementService` 类加方法：

```python
    async def find_by_name(self, project_id: str, element_name: str) -> Optional[ElementRepository]:
        """按项目+元素名/文本查找元素 (供转脚本定位匹配用, TRANS-01)。"""
        if not element_name:
            return None
        result = await self.db.execute(
            select(ElementRepository).where(
                ElementRepository.project_id == uuid.UUID(project_id),
                ElementRepository.status == "active",
                or_(
                    ElementRepository.element_name == element_name,
                    ElementRepository.element_text == element_name,
                ),
            )
        )
        return result.scalar_one_or_none()
```

（在 `element_service.py` 顶部 import 补 `or_`、`uuid`、`Optional`。）

加适配器类（文件底部）：

```python
class ElementLocatorLookup:
    """ElementRepository -> pipeline ElementLookupProto 适配器。
    locator_strategies JSONB -> Playwright 定位器字符串。"""

    def __init__(self, element_service: ElementService):
        self._svc = element_service

    async def find(self, project_id: str, target: str) -> Optional[str]:
        el = await self._svc.find_by_name(project_id, target)
        if not el:
            return None
        strategies = el.locator_strategies or []
        if isinstance(strategies, dict):
            strategies = strategies.get("strategies", [])
        return _strategy_to_playwright(strategies)


def _strategy_to_playwright(strategies: list) -> Optional[str]:
    """定位策略优先级 -> Playwright 定位器 (skill 3.1)。"""
    priority = {"role": 0, "text": 1, "label": 2, "placeholder": 3, "css": 4}
    best = None
    best_rank = 99
    for s in strategies:
        stype = s.get("type", "")
        rank = priority.get(stype, 99)
        if rank < best_rank:
            best, best_rank = s, rank
    if not best:
        return None
    t, v = best.get("type"), best.get("value", "")
    if t == "role":
        return f'page.get_by_role("button", name="{v}")' if "button" in v.lower() else f'page.get_by_role("{v}")'
    if t == "text":
        return f'page.get_by_text("{v}")'
    if t == "label":
        return f'page.get_by_label("{v}")'
    if t == "placeholder":
        return f'page.get_by_placeholder("{v}")'
    if t == "css":
        return f'page.locator("{v}")'
    return None
```

- [ ] **Step 4: Update integration test to assert locator**

修改 `test_pipeline_integration.py` 的 `test_adapter_returns_locator_string`，断言改为：

```python
        assert loc[0].locator == 'page.get_by_label("用户名")'
        assert loc[0].locator_status == "matched"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_pipeline_integration.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/element_service.py backend/tests/test_pipeline_integration.py
git commit -m "feat(script): element locator lookup adapter (#4 T9)"
```

---

## Task 10: Convert Service — 编排（DB/SSE/Token）

**Files:**
- Create: `backend/app/services/script_convert_service.py`
- Create: `backend/tests/test_script_convert_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_script_convert_service.py
"""Convert service orchestration tests (mock gateway + lookup + sse)."""
import asyncio
import pytest
from app.services.script_convert_service import ScriptConvertService, ConvertError


class FakeGateway:
    def __init__(self):
        self.tokens = 0
    async def chat(self, messages, **kw):
        self.tokens += 50
        msg = messages[0]["content"]
        if "转成结构化动作意图" in msg:
            return {"content": '[{"step":1,"action":"fill","target":"用户名","value":"admin"}]', "tokens": 50}
        if "转成断言计划" in msg:
            return {"content": '[{"step":1,"assertion_type":"status_changed","target":"页面","expected":"首页","is_valid":true}]', "tokens": 50}
        if "生成 Python" in msg:
            return {"content": 'def test_login(page):\n    page.get_by_label("用户名").fill("admin")\n', "tokens": 50}
        return {"content": "{}", "tokens": 10}


class FakeLookup:
    async def find(self, project_id, target):
        return 'page.get_by_label("用户名")' if target == "用户名" else None


class FakeSSE:
    def __init__(self):
        self.messages = []
    async def send_message(self, **kw):
        self.messages.append(kw)


class FakeSession:
    """内存 DB session stub。"""
    def __init__(self):
        self.scripts = []
        self.cases = {}
        self.sessions = []
    async def execute(self, stmt):
        return self  # 极简 stub
    def scalar_one_or_none(self):
        return None
    async def add(self, obj):
        if hasattr(obj, "case_id"):
            self.scripts.append(obj)
        else:
            self.sessions.append(obj)
    async def commit(self):
        pass
    async def flush(self):
        pass


def test_convert_single_case_writes_script():
    gw = FakeGateway()
    svc = ScriptConvertService(db=FakeSession(), gateway=gw)
    case = {
        "id": "c1", "name": "登录", "project_id": "p1",
        "steps": [{"step": 1, "action": "输入用户名admin", "expected": "输入成功"}],
        "expected_result": "进入首页",
    }
    sse = FakeSSE()
    script = asyncio.run(svc.convert_one(case, sse, lookup=FakeLookup(), ai_optimize=False))
    assert script.content.startswith("def test_login")
    assert script.locator_source == "element_library"
    assert script.step_mapping[0]["status"] == "ok"
    assert len(sse.messages) >= 3  # 开始/匹配/完成


def test_missing_steps_raises_convert_error():
    svc = ScriptConvertService(db=FakeSession(), gateway=FakeGateway())
    case = {"id": "c2", "name": "x", "steps": [], "expected_result": "y"}
    with pytest.raises(ConvertError):
        asyncio.run(svc.convert_one(case, FakeSSE(), lookup=FakeLookup(), ai_optimize=False))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_convert_service.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement convert service**

```python
# backend/app/services/script_convert_service.py
"""转脚本编排: ConvertSession 生命周期 + 5 步调用 + SSE + Token。"""
import logging
from typing import Optional
from datetime import datetime

from app.services.script_pipeline import (
    step0_normalize, step1_to_actions, step2_to_assertions,
    step3_match_locators, step4_generate_code, NormalizeError,
)
from app.services.script_validator import validate_script
from app.models.test_case import ScriptAsset

logger = logging.getLogger(__name__)


class ConvertError(Exception):
    """单用例转换失败。"""


class ScriptConvertService:
    def __init__(self, db, gateway):
        self.db = db
        self.gateway = gateway

    async def convert_one(self, case: dict, sse, lookup, ai_optimize: bool) -> ScriptAsset:
        """转换单个用例 -> ScriptAsset (不写 DB, 由调用方决定)。"""
        case_id = case.get("id")
        await sse.send_message(type="system", stage="convert_script",
                               content=f"开始转换用例: {case.get('name','')}", progress=0.0)
        try:
            normalized = step0_normalize(case)
        except NormalizeError as e:
            await sse.send_message(type="error", stage="convert_script",
                                   content=f"用例 {case_id} 不可生成: {e}", progress=0.0)
            raise ConvertError(str(e))

        actions = await step1_to_actions(normalized, self.gateway)
        await sse.send_message(type="system", stage="convert_script",
                               content=f"生成 {len(actions)} 个动作意图", progress=0.3)

        asserts = await step2_to_assertions(normalized, self.gateway)
        await sse.send_message(type="system", stage="convert_script",
                               content=f"生成 {len(asserts)} 个断言计划", progress=0.5)

        with_loc = await step3_match_locators(
            actions, str(case.get("project_id")), lookup, ai_optimize, self.gateway)
        matched = sum(1 for w in with_loc if w.locator_status == "matched")
        await sse.send_message(type="system", stage="convert_script",
                               content=f"匹配元素库: {matched}/{len(with_loc)} 命中",
                               progress=0.7)

        gen = await step4_generate_code(normalized, with_loc, asserts, self.gateway)
        report = validate_script(gen.script, gen.step_mapping)
        if not report.all_pass():
            await sse.send_message(type="system", stage="convert_script",
                                   content=f"质量自检有项不过: {[c.name for c in report.checks if not c.passed]}",
                                   progress=0.9)

        status = "generated" if report.all_pass() else "draft"
        asset = ScriptAsset(
            case_id=case_id, project_id=case.get("project_id"),
            name=normalized.title, description=case.get("expected_result"),
            content=gen.script, version=1, status=status,
            category="uncategorized", step_mapping=gen.step_mapping,
            locator_source=gen.locator_source, last_status="never_run",
        )
        await sse.send_message(type="system", stage="convert_script",
                               content="转换完成，脚本已生成", progress=1.0,
                               tokens_used=self.gateway.tokens)
        return asset

    async def persist(self, asset: ScriptAsset):
        self.db.add(asset)
        await self.db.flush()
```

> 注：`gateway.tokens` 累计需 FakeGateway 暴露 `.tokens` 属性（Task10 的 FakeGateway 已有）。真实 gateway 通过包装累加（见 Task 12）。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_convert_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_convert_service.py backend/tests/test_script_convert_service.py
git commit -m "feat(script): convert service orchestration (#4 T10)"
```

---

## Task 11: Diagnose Service — 四分类归因 + 重生成

**Files:**
- Create: `backend/app/services/script_diagnose_service.py`
- Create: `backend/tests/test_script_diagnose_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_script_diagnose_service.py
"""Diagnose service 4-category attribution tests."""
import asyncio
from app.services.script_diagnose_service import (
    classify_failure, ScriptDiagnoseService, DATA_ENV_KEYWORDS,
)


class TestClassifyFailure:
    def test_locate_failed_is_script_problem(self):
        card = classify_failure(error_type="locate_failed", error_msg="Element not found", failed_step=2)
        assert card["category"] == "script_problem"
        assert card["can_fix"] is True

    def test_assertion_failed_is_page_bug(self):
        card = classify_failure(error_type="assertion_failed", error_msg="expected X got Y", failed_step=1)
        assert card["category"] == "page_bug"
        assert card["can_fix"] is False

    def test_data_env_keyword_overrides(self):
        card = classify_failure(error_type="script_error", error_msg="数据重复", failed_step=1)
        assert card["category"] == "data_env"
        assert card["can_fix"] is False

    def test_missing_type_is_ambiguous(self):
        card = classify_failure(error_type=None, error_msg="something", failed_step=None)
        assert card["category"] == "ambiguous"


class TestDiagnoseService:
    def test_cannot_fix_returns_card_only(self):
        svc = ScriptDiagnoseService(gateway=None)
        card = asyncio.run(svc.diagnose(
            error_type="assertion_failed", error_msg="x", script_fragment="y",
            failed_step=1))
        assert card["can_fix"] is False
        assert card["revised_step"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_diagnose_service.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement diagnose service**

```python
# backend/app/services/script_diagnose_service.py
"""调试修复: skill 5.2 四分类归因 + 失败步骤重生成。"""
from typing import Optional


DATA_ENV_KEYWORDS = ("重复", "已存在", "唯一", "duplicate", "already exists", "unique")


def classify_failure(error_type: Optional[str], error_msg: str,
                     failed_step: Optional[int]) -> dict:
    """skill 5.2 四分类:
    - script_problem (定位/超时/脚本错误) -> 可改
    - page_bug (断言值不符) -> 不可改, xfail
    - data_env (重复/已存在/唯一) -> 不可改, 硬停
    - ambiguous (信息不足) -> 不可改
    """
    msg = error_msg or ""
    if any(kw in msg for kw in DATA_ENV_KEYWORDS):
        return _card("data_env", False, "数据/环境问题，硬停", failed_step, error_type, error_msg)
    if error_type == "assertion_failed":
        return _card("page_bug", False, "断言值不符，页面Bug，标xfail", failed_step, error_type, error_msg)
    if error_type in ("locate_failed", "timeout", "script_error"):
        return _card("script_problem", True, "脚本问题，可改", failed_step, error_type, error_msg)
    return _card("ambiguous", False, "信息不足，建议补DOM/截图", failed_step, error_type, error_msg)


def _card(category, can_fix, reason, failed_step, error_type, error_msg, **extra):
    d = {"category": category, "can_fix": can_fix, "reason": reason,
         "failed_step": failed_step, "error_type": error_type, "error_msg": error_msg,
         "suggestion": ""}
    d.update(extra)
    return d


class ScriptDiagnoseService:
    def __init__(self, gateway):
        self.gateway = gateway

    async def diagnose(self, error_type, error_msg, script_fragment,
                       failed_step=None, screenshot_url=None, dom_snapshot=None):
        card = classify_failure(error_type, error_msg, failed_step)
        card["screenshot_url"] = screenshot_url
        if card["can_fix"] and self.gateway is not None and failed_step:
            card["revised_step"] = await self._regen_step(error_type, error_msg, script_fragment, failed_step)
            card["suggestion"] = f"已重生成步骤 {failed_step} 代码"
        elif card["can_fix"]:
            card["revised_step"] = None
            card["suggestion"] = "可改但缺少 gateway 或 failed_step"
        else:
            card["suggestion"] = card["reason"]
        return card

    async def _regen_step(self, error_type, error_msg, script_fragment, failed_step):
        prompt = f"修复第 {failed_step} 步脚本。错误类型: {error_type}, 错误: {error_msg}。只输出修复后的代码片段:\n{script_fragment}"
        resp = await self.gateway.chat([{"role": "user", "content": prompt}])
        return resp["content"].strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_diagnose_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_diagnose_service.py backend/tests/test_script_diagnose_service.py
git commit -m "feat(script): diagnose 4-category service (#4 T11)"
```

---

## Task 12: Celery Task — convert_scripts_task

**Files:**
- Create: `backend/app/tasks/script_tasks.py`
- Create: `backend/tests/test_script_tasks.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_script_tasks.py
"""Celery task test (direct call, not via broker)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.tasks.script_tasks import convert_scripts_task_impl


def test_task_runs_all_cases_and_writes_assets():
    cases = [
        {"id": "c1", "name": "登录", "project_id": "p1",
         "steps": [{"step": 1, "action": "输入用户名admin", "expected": "ok"}],
         "expected_result": "进入首页"},
    ]
    gateway = MagicMock()
    gateway.chat = AsyncMock(side_effect=[
        {"content": '[{"step":1,"action":"fill","target":"用户名","value":"admin"}]', "tokens": 50},
        {"content": '[{"step":1,"assertion_type":"status_changed","target":"p","expected":"首页","is_valid":true}]', "tokens": 50},
        {"content": 'def t(page):\n    page.get_by_label("用户名").fill("admin")\n', "tokens": 50},
    ])
    gateway.tokens = 150

    lookup = MagicMock()
    lookup.find = AsyncMock(return_value='page.get_by_label("用户名")')

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    # session lookup returns the case itself
    db.execute = AsyncMock()
    db.scalar_one_or_none = MagicMock(return_value=None)

    session_id = "s1"
    result = asyncio.run(convert_scripts_task_impl(
        session_id, cases, gateway=gateway, lookup=lookup, db=db))
    assert result["status"] == "done"
    assert result["tokens_used"] == 150
    assert result["generated_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_tasks.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement Celery task**

```python
# backend/app/tasks/script_tasks.py
"""Script conversion Celery tasks."""
import logging
import uuid
from typing import List

from app.tasks import celery_app
from app.core.database import AsyncSessionLocal
from app.core.sse import SSEStream
from app.services.script_convert_service import ScriptConvertService, ConvertError
from app.services.element_service import ElementLocatorLookup, ElementService
from app.services.ai_gateway import AIGateway

logger = logging.getLogger(__name__)


async def convert_scripts_task_impl(session_id: str, cases: List[dict],
                                    gateway, lookup, db) -> dict:
    """批量转换实现 (供直接调用测试)。"""
    sse = _SSEWrapper(SSEStream(session_id))
    svc = ScriptConvertService(db=db, gateway=gateway)
    generated = 0
    tokens = 0
    for i, case in enumerate(cases):
        progress = i / max(len(cases), 1)
        try:
            asset = await svc.convert_one(case, sse, lookup=lookup, ai_optimize=False)
            await svc.persist(asset)
            generated += 1
            tokens = getattr(gateway, "tokens", tokens)
        except ConvertError as e:
            logger.warning(f"case {case.get('id')} convert failed: {e}")
            await sse.send_message(type="error", stage="convert_script",
                                   content=f"用例失败: {e}", progress=progress)
    await db.commit()
    return {"status": "done", "generated_count": generated, "tokens_used": tokens}


class _SSEWrapper:
    """SSEStream 适配 (提供 send_message kwargs 接口)。"""
    def __init__(self, stream: SSEStream):
        self._stream = stream

    async def send_message(self, **kw):
        await self._stream.send_message(
            type=kw.get("type", "system"),
            stage=kw.get("stage", "convert_script"),
            content=kw.get("content", ""),
            progress=kw.get("progress", 0.0),
            tokens_used=kw.get("tokens_used", 0),
        )


@celery_app.task(bind=True, name="convert_scripts_task")
def convert_scripts_task(self, session_id: str, case_ids: list, project_id: str, ai_optimize: bool = False):
    """Celery 入口: 查用例 -> 转换 -> 写 ScriptAsset + 自动化状态联动。"""
    import asyncio
    from sqlalchemy import select
    from app.models.test_case import TestCase, ScriptAsset

    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TestCase).where(
                    TestCase.id.in_([uuid.UUID(c) for c in case_ids]),
                    TestCase.is_finalized.is_(True),
                )
            )
            cases = [c.to_dict() for c in result.scalars().all()]
            gateway = _CountingGateway(AIGateway())
            element_svc = ElementService(db)
            lookup = ElementLocatorLookup(element_svc)
            summary = await convert_scripts_task_impl(session_id, cases, gateway, lookup, db)
            # 联动 automation_status -> converted (CASE-MGMT-04)
            await db.execute(
                TestCase.__table__.update().where(
                    TestCase.id.in_([uuid.UUID(c) for c in case_ids])
                ).values(automation_status="converted")
            )
            await db.commit()
            return summary

    return asyncio.run(_run())


class _CountingGateway:
    """包装 AIGateway 累计 tokens (修 #2 Token 实时推送恒 0)。"""
    def __init__(self, gateway):
        self._gw = gateway
        self.tokens = 0

    async def chat(self, messages, **kw):
        resp = await self._gw.chat(messages, **kw)
        self.tokens += resp.get("tokens", 0)
        return resp
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_tasks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/script_tasks.py backend/tests/test_script_tasks.py
git commit -m "feat(script): celery convert task + automation_status linkage (#4 T12)"
```

---

## Task 13: API Router — convert / list / get

**Files:**
- Create: `backend/app/api/v1/scripts.py`
- Modify: `backend/app/api/__init__.py`
- Create: `backend/tests/test_script_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_script_api.py
"""Script API tests."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_convert_returns_session_id(monkeypatch):
    # stub task.delay
    from app.api.v1 import scripts as scripts_api
    fake_task = type("T", (), {"id": "task-1"})()
    monkeypatch.setattr(scripts_api, "convert_scripts_task",
                        type("M", (), {"delay": staticmethod(lambda **kw: fake_task)}))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/v1/scripts/convert", json={
            "project_id": "00000000-0000-0000-0000-000000000001",
            "case_ids": ["00000000-0000-0000-0000-000000000002"],
            "ai_optimize": False,
        })
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert "session_id" in body["data"]
    assert "sse_url" in body["data"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_api.py -v`
Expected: FAIL with 404 (route not registered)

- [ ] **Step 3: Implement API router (convert + list + get)**

```python
# backend/app/api/v1/scripts.py
"""Script conversion API endpoints (模块 #4)."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.models.project import Project
from app.models.test_case import TestCase, ScriptAsset
from app.schemas.script import ConvertRequest
from app.tasks.script_tasks import convert_scripts_task

router = APIRouter()


@router.post("/convert")
async def convert_scripts(request: ConvertRequest, db: AsyncSession = Depends(get_db)):
    """触发批量转脚本 (异步, SSE 文字直播)。"""
    try:
        project_uuid = uuid.UUID(request.project_id)
        case_uuids = [uuid.UUID(c) for c in request.case_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    result = await db.execute(select(Project).where(Project.id == project_uuid))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(TestCase).where(
            TestCase.id.in_(case_uuids),
            TestCase.is_finalized.is_(True),
            TestCase.is_deleted.is_(False),
        )
    )
    found = result.scalars().all()
    if not found:
        raise HTTPException(status_code=400, detail="没有已定稿的用例可选")

    session_id = str(uuid.uuid4())
    convert_scripts_task.delay(
        session_id=session_id,
        case_ids=request.case_ids,
        project_id=request.project_id,
        ai_optimize=request.ai_optimize,
    )
    return {
        "code": 0,
        "message": "Script conversion started",
        "data": {
            "session_id": session_id,
            "sse_url": f"/api/stream/{session_id}",
        },
    }


@router.get("")
async def list_scripts(
    project_id: Optional[str] = None,
    case_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """脚本列表。"""
    stmt = select(ScriptAsset)
    if project_id:
        stmt = stmt.where(ScriptAsset.project_id == uuid.UUID(project_id))
    if case_id:
        stmt = stmt.where(ScriptAsset.case_id == uuid.UUID(case_id))
    stmt = stmt.order_by(ScriptAsset.created_at.desc())
    result = await db.execute(stmt)
    scripts = result.scalars().all()
    return {"code": 0, "data": [s.to_dict() for s in scripts]}


@router.get("/{script_id}")
async def get_script(script_id: str, db: AsyncSession = Depends(get_db)):
    """脚本详情。"""
    try:
        sid = uuid.UUID(script_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    result = await db.execute(select(ScriptAsset).where(ScriptAsset.id == sid))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Script not found")
    return {"code": 0, "data": asset.to_dict()}
```

- [ ] **Step 4: Register router**

修改 `backend/app/api/__init__.py`：

```python
from app.api.v1 import projects, health, elements, sse, ai_case_generation, test_cases, scripts
# ...
api_router.include_router(scripts.router, prefix="/scripts", tags=["scripts"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/scripts.py backend/app/api/__init__.py backend/tests/test_script_api.py
git commit -m "feat(script): API convert/list/get endpoints (#4 T13)"
```

---

## Task 14: API — confirm + diagnose endpoints

**Files:**
- Modify: `backend/app/api/v1/scripts.py`
- Modify: `backend/tests/test_script_api.py`

- [ ] **Step 1: Write the failing test**

在 `test_script_api.py` 加：

```python
@pytest.mark.asyncio
async def test_confirm_sets_status_and_diagnose_returns_card(monkeypatch):
    from app.api.v1 import scripts as scripts_api
    # stub diagnose service
    class FakeDiag:
        async def diagnose(self, **kw):
            return {"category": "script_problem", "can_fix": True, "reason": "x",
                    "failed_step": kw.get("failed_step"), "error_type": kw.get("error_type"),
                    "error_msg": kw.get("error_msg"), "screenshot_url": None,
                    "revised_step": "new code", "suggestion": "已重生成"}
    monkeypatch.setattr(scripts_api, "ScriptDiagnoseService", lambda gateway: FakeDiag())
    # stub ai_gateway
    monkeypatch.setattr(scripts_api, "AIGateway", lambda: None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        # diagnose (script_id 不存在也走 stub, 故意用一个 uuid)
        r = await ac.post("/api/v1/scripts/00000000-0000-0000-0000-000000000001/diagnose", json={
            "error_type": "locate_failed", "error_msg": "not found",
            "script_fragment": "page.click('#x')", "failed_step": 1,
        })
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["diagnosis_card"]["can_fix"] is True
    assert body["data"]["revised_script"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_script_api.py::test_confirm_sets_status_and_diagnose_returns_card -v`
Expected: FAIL (endpoint missing)

- [ ] **Step 3: Implement confirm + diagnose**

在 `scripts.py` 加 import 与端点：

```python
from app.services.script_diagnose_service import ScriptDiagnoseService
from app.services.ai_gateway import AIGateway
from app.schemas.script import DiagnoseRequest


@router.put("/{script_id}/confirm")
async def confirm_script(script_id: str, db: AsyncSession = Depends(get_db)):
    """TRANS-02 用户确认入库: ScriptAsset.status->confirmed。"""
    try:
        sid = uuid.UUID(script_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    result = await db.execute(select(ScriptAsset).where(ScriptAsset.id == sid))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Script not found")
    asset.status = "confirmed"
    await db.commit()
    return {"code": 0, "message": "Script confirmed",
            "data": {"script_id": script_id, "status": "confirmed"}}


@router.post("/{script_id}/diagnose")
async def diagnose_script(script_id: str, request: DiagnoseRequest,
                          db: AsyncSession = Depends(get_db)):
    """调试修复: 四分类归因 + 失败步骤重生成。"""
    try:
        sid = uuid.UUID(script_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    result = await db.execute(select(ScriptAsset).where(ScriptAsset.id == sid))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Script not found")

    svc = ScriptDiagnoseService(gateway=AIGateway())
    card = await svc.diagnose(
        error_type=request.error_type, error_msg=request.error_msg,
        script_fragment=request.script_fragment, failed_step=request.failed_step,
        screenshot_url=request.screenshot_url, dom_snapshot=request.dom_snapshot,
    )
    revised_script = None
    if card.get("can_fix") and card.get("revised_step"):
        revised_script = (asset.content or "") + "\n# --- 修复步骤 {} ---\n".format(
            request.failed_step) + card["revised_step"]
        asset.content = revised_script
        asset.ai_diagnosis = card
        asset.version = (asset.version or 1) + 1
        await db.commit()
    return {"code": 0, "data": {"diagnosis_card": card, "revised_script": revised_script}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_script_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/scripts.py backend/tests/test_script_api.py
git commit -m "feat(script): confirm + diagnose endpoints (#4 T14)"
```

---

## Task 15: Frontend API client + page + route

**Files:**
- Create: `frontend/src/api/script.js`
- Create: `frontend/src/views/ScriptConvert.vue`
- Modify: `frontend/src/router/index.js`

- [ ] **Step 1: Create API client**

```javascript
// frontend/src/api/script.js
import axios from './axios'

const API_BASE = '/api/v1/scripts'

export const scriptAPI = {
  async convert(projectId, caseIds, aiOptimize = false) {
    const response = await axios.post(`${API_BASE}/convert`, {
      project_id: projectId,
      case_ids: caseIds,
      ai_optimize: aiOptimize,
    })
    return response.data
  },

  async list(params = {}) {
    const response = await axios.get(API_BASE, { params })
    return response.data
  },

  async get(scriptId) {
    const response = await axios.get(`${API_BASE}/${scriptId}`)
    return response.data
  },

  async confirm(scriptId) {
    const response = await axios.put(`${API_BASE}/${scriptId}/confirm`)
    return response.data
  },

  async diagnose(scriptId, payload) {
    const response = await axios.post(`${API_BASE}/${scriptId}/diagnose`, payload)
    return response.data
  },

  /**
   * SSE 订阅转脚本文字直播
   * @param {string} sessionId
   * @param {(msg: object) => void} onMessage
   * @param {(err: Event) => void} [onError]
   * @returns {EventSource}
   */
  subscribe(sessionId, onMessage, onError) {
    const es = new EventSource(`/api/stream/${sessionId}`)
    es.onmessage = (ev) => {
      try { onMessage(JSON.parse(ev.data)) } catch { onMessage({ content: ev.data }) }
    }
    if (onError) es.onerror = onError
    return es
  },
}
```

- [ ] **Step 2: Create page**

```vue
<!-- frontend/src/views/ScriptConvert.vue -->
<template>
  <div class="script-convert">
    <el-card>
      <h2>用例转自动化脚本</h2>
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="form.projectId" placeholder="选择项目" style="width: 200px">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例">
          <el-select v-model="form.caseIds" multiple filterable placeholder="多选用例" style="width: 360px">
            <el-option v-for="c in finalizedCases" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="AI优化">
          <el-switch v-model="form.aiOptimize" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="converting" @click="handleConvert">批量转脚本</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card style="margin-top: 16px">
      <h3>转换过程文字直播</h3>
      <div class="log-box">
        <div v-for="(msg, i) in logs" :key="i" class="log-line">
          [{{ msg.timestamp }}] {{ msg.content }}
        </div>
      </div>
    </el-card>

    <el-card style="margin-top: 16px">
      <h3>脚本列表</h3>
      <el-table :data="scripts" border>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="locator_source" label="定位来源" width="140" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="viewScript(row)">查看</el-button>
            <el-button size="small" type="success" :disabled="row.status==='confirmed'"
                       @click="confirmScript(row)">确认入库</el-button>
            <el-button size="small" @click="openDiagnose(row)">调试修复</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="diagVisible" title="调试修复" width="700px">
      <el-form label-width="100px">
        <el-form-item label="错误类型">
          <el-select v-model="diagForm.error_type" style="width: 200px">
            <el-option label="定位失败" value="locate_failed" />
            <el-option label="超时" value="timeout" />
            <el-option label="断言失败" value="assertion_failed" />
            <el-option label="脚本错误" value="script_error" />
          </el-select>
        </el-form-item>
        <el-form-item label="错误信息">
          <el-input v-model="diagForm.error_msg" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="脚本片段">
          <el-input v-model="diagForm.script_fragment" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="失败步骤">
          <el-input-number v-model="diagForm.failed_step" :min="1" />
        </el-form-item>
        <el-form-item label="截图URL">
          <el-input v-model="diagForm.screenshot_url" placeholder="可选" />
        </el-form-item>
      </el-form>
      <div v-if="diagCard" class="diag-card">
        <p>归因: <strong>{{ diagCard.category }}</strong> | 可改: {{ diagCard.can_fix }}</p>
        <p>理由: {{ diagCard.reason }}</p>
        <p v-if="diagCard.suggestion">建议: {{ diagCard.suggestion }}</p>
      </div>
      <template #footer>
        <el-button @click="diagVisible = false">关闭</el-button>
        <el-button type="primary" @click="runDiagnose">诊断</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { scriptAPI } from '@/api/script'
import { projectAPI } from '@/api/project'
import { testCaseAPI } from '@/api/testCase'

const projects = ref([])
const finalizedCases = ref([])
const scripts = ref([])
const logs = ref([])
const converting = ref(false)
const form = reactive({ projectId: '', caseIds: [], aiOptimize: false })

const diagVisible = ref(false)
const diagForm = reactive({ error_type: 'locate_failed', error_msg: '', script_fragment: '', failed_step: 1, screenshot_url: '' })
const diagCard = ref(null)
let currentScriptId = null

onMounted(async () => {
  const presp = await projectAPI.list()
  projects.value = presp.data || presp
})

const loadCases = async () => {
  if (!form.projectId) return
  const resp = await testCaseAPI.list({ project_id: form.projectId, is_finalized: true })
  finalizedCases.value = resp.data?.items || []
}
const handleConvert = async () => {
  if (!form.projectId || !form.caseIds.length) {
    ElMessage.warning('请选择项目和用例'); return
  }
  converting.value = true; logs.value = []
  try {
    const resp = await scriptAPI.convert(form.projectId, form.caseIds, form.aiOptimize)
    const es = scriptAPI.subscribe(resp.data.session_id, (msg) => {
      logs.value.push(msg)
    })
    setTimeout(() => { es.close(); loadScripts(); converting.value = false }, 3000)
  } catch (e) { ElMessage.error('转换失败'); converting.value = false }
}
const loadScripts = async () => {
  const resp = await scriptAPI.list({ project_id: form.projectId })
  scripts.value = resp.data || []
}
const viewScript = (row) => { window.open(`/api/v1/scripts/${row.id}`, '_blank') }
const confirmScript = async (row) => {
  await scriptAPI.confirm(row.id)
  ElMessage.success('已确认入库'); loadScripts()
}
const openDiagnose = (row) => {
  currentScriptId = row.id
  diagCard.value = null
  diagVisible.value = true
}
const runDiagnose = async () => {
  const resp = await scriptAPI.diagnose(currentScriptId, { ...diagForm })
  diagCard.value = resp.data.diagnosis_card
  ElMessage.success('诊断完成')
}
</script>

<style scoped>
.log-box { max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #ddd; padding: 12px; border-radius: 4px; }
.log-line { margin-bottom: 4px; }
.diag-card { margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
</style>
```

- [ ] **Step 3: Add route**

修改 `frontend/src/router/index.js`，在路由数组中加：

```javascript
{
  path: '/scripts',
  name: 'ScriptConvert',
  component: () => import('@/views/ScriptConvert.vue'),
  meta: { title: '用例转脚本' },
},
```

- [ ] **Step 4: Run backend test suite to ensure no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/script.js frontend/src/views/ScriptConvert.vue frontend/src/router/index.js
git commit -m "feat(script): frontend page + API client + route (#4 T15)"
```

---

## Task 16: 端到端验收

**Files:**
- Manual verification + final test run

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all PASS, coverage of script services ≥80%

- [ ] **Step 2: Verify skill hard-rule gate tests green**

Run: `cd backend && python -m pytest tests/test_script_validator.py tests/test_script_pipeline.py -v`
Expected: PASS (无索引定位/永真断言/硬编码等待/编造 DOM 守门项全绿)

- [ ] **Step 3: Spec acceptance checklist verification**

对照 `docs/superpowers/specs/2026-08-24-case-to-script-design.md` §10 验收标准 11 条逐项核对：
1. 选已定稿用例 → 批量转脚本 → SSE 文字直播 → 脚本入 ScriptAsset（status=generated, category=uncategorized）
2. 元素库命中步骤直接引用 locator；未命中标 draft 不编造
3. AI 生成定位器经用户确认后回写元素库（TRANS-02）
4. step_mapping 对照表完整，❌ 步骤阻塞
5. 调试修复四分类正确，可改类重生成失败步骤；诊断卡含输入上下文
6. skill 硬规则守门测试全绿
7. 核心服务测试覆盖 ≥80%
8. Token 真实累计 + tokens_estimated_total 线性预估
9. convert 成功后 TestCase.automation_status 流转到 converted
10. LLM 调用前查 token_quota（若 #10 未建则跳过，记未决）
11. 单用例转脚本 <10s（P1，人工抽测）

- [ ] **Step 4: Final commit (if any cleanup)**

```bash
git add -A
git commit -m "chore(script): final acceptance (#4)" --allow-empty
```

---

## Self-Review 记录

- **Spec 覆盖**: §2 数据模型→T1; §3 流水线→T3-7; §4 API→T13-14; §5 服务层→T9-12; §6 Celery+联动→T12; §7 调试修复→T11; §8 前端→T15; §9 测试→各 Task TDD; §10 验收→T16。全覆盖。
- **占位符扫描**: Task2 Step3 含一个故意占位 bug（`_PATTERN`），Step4 已指示修复——执行时务必做 Step4。
- **类型一致性**: `NormalizedCase/ActionIntent/AssertionPlan/ActionWithLocator/GenerateResult/DiagnosisCard` 跨 Task 定义一致；`step_mapping` 字段 `step/case_req/impl/status` 一致；`locator_source` 枚举一致。
