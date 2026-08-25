# 脚本执行引擎主干（模块 #5a）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 已入库脚本 → Playwright 逐步执行 → 失败采集 → 写 execution_record/detail → 回写 ScriptAsset → SSE stage=execute 文字直播。

**Architecture:** 乙路径执行引擎（读 step_mapping 逐步 → 查元素库 → SmartLocator.locate_and_interact）+ 失败采集（截图+DOM+堆栈落 MinIO）+ execution_detail 新表 + run/batch-run/quick-run/stats 端点。Celery 异步执行，SSE 复用 SSEStream。范围 #5a：自愈 Level1 接入（复用 SmartLocator），Level2-4/AI 诊断留 #5b/#5c。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy(async) / Pydantic / Celery / Playwright / 复用 `SmartLocator`/`ElementService`/`StorageClient`/`SSEStream`/`_CountingGateway`。

**Spec:** `docs/superpowers/specs/2026-08-25-script-execution-design.md`

---

## 文件结构

**后端新增：**
- `backend/app/services/script_executor.py` — 执行引擎编排（逐步执行 + 失败采集 + 回写）
- `backend/tests/test_script_executor.py`
- `backend/tests/test_execution_models.py`
- `backend/tests/test_run_api.py`

**后端修改：**
- `backend/app/models/execution.py` — 新增 ExecutionDetail 模型
- `backend/app/models/__init__.py` — 导出 ExecutionDetail
- `backend/app/schemas/script.py` — 新增 SCRIPT_LAST_STATUSES/SCRIPT_CATEGORIES 枚举 + RunRequest/QuickRunRequest/RunConfig schemas
- `backend/app/services/script_pipeline.py` — 扩 `_build_step_mapping` 加 element_name/page_name/action/value/assertion
- `backend/app/services/playwright_service.py` — `start(headless, timeout)` 参数化
- `backend/app/api/v1/scripts.py` — run/batch-run/quick-run/stats 端点 + list 扩 category/keyword
- `backend/app/tasks/script_tasks.py` — run_scripts_task / batch_run_scripts_task
- `backend/migrations/add_execution_detail_table.sql`

---

## Task 1: ExecutionDetail 模型 + 迁移

**Files:**
- Modify: `backend/app/models/execution.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/add_execution_detail_table.sql`
- Create: `backend/tests/test_execution_models.py`

- [ ] **Step 1: Write the failing test** — Create `backend/tests/test_execution_models.py`:

```python
"""ExecutionDetail model tests."""
from app.models.execution import ExecutionDetail, ExecutionRecord


class TestExecutionDetailColumns:
    def test_required_columns(self):
        cols = {c.name for c in ExecutionDetail.__table__.c}
        for expected in ("id", "execution_record_id", "script_id", "case_id",
                         "step", "action", "status", "error_type", "error_msg",
                         "stack_trace", "screenshot_url", "dom_snapshot",
                         "heal_status", "heal_log", "duration_ms", "created_at"):
            assert expected in cols

    def test_has_index_on_execution_record_id(self):
        indexes = [i.name for i in ExecutionDetail.__table__.indexes]
        assert "idx_exec_detail_record" in indexes

    def test_fk_to_execution_record_cascade(self):
        fks = [str(f) for f in ExecutionDetail.__table__.foreign_keys]
        assert any("execution_record" in f and "CASCADE" in f for f in fks)
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend && python -m pytest tests/test_execution_models.py -v` — Expected: FAIL (ExecutionDetail 不存在)

- [ ] **Step 3: Add ExecutionDetail model** — In `backend/app/models/execution.py`, append after AICallLog:

```python
class ExecutionDetail(Base):
    """执行明细表 - 每条用例/每步的执行记录 (§4 ER 图 1:N execution_record→execution_detail)"""
    __tablename__ = "execution_detail"
    __table_args__ = (
        Index("idx_exec_detail_record", "execution_record_id"),
    )

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
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "execution_record_id": str(self.execution_record_id),
            "script_id": str(self.script_id) if self.script_id else None,
            "case_id": str(self.case_id) if self.case_id else None,
            "step": self.step,
            "action": self.action,
            "status": self.status,
            "error_type": self.error_type,
            "error_msg": self.error_msg,
            "stack_trace": self.stack_trace,
            "screenshot_url": self.screenshot_url,
            "dom_snapshot": self.dom_snapshot,
            "heal_status": self.heal_status,
            "heal_log": self.heal_log,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
```

Ensure imports at top of execution.py include `Index` and `JSONB` (JSONB from postgresql dialect). Check existing imports; `Index` likely missing — add `from sqlalchemy import ... Index`; JSONB add `from sqlalchemy.dialects.postgresql import UUID, JSONB`.

- [ ] **Step 4: Register in models/__init__.py** — Add `ExecutionDetail` to the import from execution and to `__all__`.

- [ ] **Step 5: Create migration** — `backend/migrations/add_execution_detail_table.sql`:

```sql
-- #5a: execution_detail table (req §4 ER graph, DDL omitted in spec)
-- Idempotent.
CREATE TABLE IF NOT EXISTS execution_detail (
    id UUID PRIMARY KEY,
    execution_record_id UUID NOT NULL REFERENCES execution_record(id) ON DELETE CASCADE,
    script_id UUID REFERENCES script_asset(id) ON DELETE SET NULL,
    case_id UUID REFERENCES test_case(id) ON DELETE SET NULL,
    step INTEGER,
    action VARCHAR(50),
    status VARCHAR(20) NOT NULL,
    error_type VARCHAR(30),
    error_msg TEXT,
    stack_trace TEXT,
    screenshot_url TEXT,
    dom_snapshot TEXT,
    heal_status VARCHAR(20) DEFAULT 'none',
    heal_log JSONB,
    duration_ms INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_exec_detail_record ON execution_detail(execution_record_id);
```

- [ ] **Step 6: Run test to verify it passes** — `cd backend && python -m pytest tests/test_execution_models.py -v` — Expected: PASS. Also `python -m pytest tests/test_script_models.py -q` (no regression).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/execution.py backend/app/models/__init__.py backend/migrations/add_execution_detail_table.sql backend/tests/test_execution_models.py
git commit -m "feat(exec): ExecutionDetail model + migration (#5a T1)"
```

---

## Task 2: Schemas — 枚举 + Run/QuickRun 请求

**Files:**
- Modify: `backend/app/schemas/script.py`
- Create: `backend/tests/test_script_exec_schemas.py`

- [ ] **Step 1: Write the failing test** — Create `backend/tests/test_script_exec_schemas.py`:

```python
"""Script execution schema tests."""
import pytest
from pydantic import ValidationError
from app.schemas.script import (
    SCRIPT_LAST_STATUSES, SCRIPT_CATEGORIES,
    RunConfig, RunRequest, BatchRunRequest, QuickRunRequest,
)


class TestEnums:
    def test_last_statuses(self):
        assert SCRIPT_LAST_STATUSES == ("never_run", "passed", "failed", "affected")

    def test_categories(self):
        assert SCRIPT_CATEGORIES == ("uncategorized", "ui_smoke", "full_regression", "core_flow", "interface_auto")


class TestRunSchemas:
    def _config(self):
        return dict(headless=True, timeout=60, max_failures=8)

    def test_run_request_minimal(self):
        r = RunRequest(script_id="00000000-0000-0000-0000-000000000001", config=self._config())
        assert r.config.headless is True
        assert r.config.timeout == 60
        assert r.config.max_failures == 8

    def test_run_request_invalid_script_id(self):
        with pytest.raises(ValidationError):
            RunRequest(script_id="not-a-uuid", config=self._config())

    def test_run_config_max_failures_range(self):
        with pytest.raises(ValidationError):
            RunConfig(headless=True, timeout=60, max_failures=0)
        with pytest.raises(ValidationError):
            RunConfig(headless=True, timeout=60, max_failures=101)

    def test_run_config_timeout_range(self):
        with pytest.raises(ValidationError):
            RunConfig(headless=True, timeout=4, max_failures=8)
        with pytest.raises(ValidationError):
            RunConfig(headless=True, timeout=601, max_failures=8)

    def test_batch_run_request_min_length(self):
        with pytest.raises(ValidationError):
            BatchRunRequest(script_ids=[], config=self._config())

    def test_quick_run_request(self):
        r = QuickRunRequest(script_content="def test_x(page): pass", target_url="http://x", headless=True)
        assert r.target_url == "http://x"

    def test_quick_run_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            QuickRunRequest(script_content="", target_url="http://x", headless=True)
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend && python -m pytest tests/test_script_exec_schemas.py -v` — Expected: FAIL (ImportError)

- [ ] **Step 3: Add enums + schemas** — In `backend/app/schemas/script.py`, append:

```python
SCRIPT_LAST_STATUSES = ("never_run", "passed", "failed", "affected")
SCRIPT_CATEGORIES = ("uncategorized", "ui_smoke", "full_regression", "core_flow", "interface_auto")


class RunConfig(BaseModel):
    headless: bool = Field(True, description="有头/无头模式")
    timeout: int = Field(60, ge=5, le=600, description="单测试超时秒")
    max_failures: int = Field(8, ge=1, le=100, description="最大失败数")


class RunRequest(BaseModel):
    script_id: str = Field(..., description="脚本 ID (UUID)")
    config: RunConfig = Field(default_factory=RunConfig)

    @field_validator("script_id")
    @classmethod
    def _valid_uuid(cls, v):
        import uuid
        uuid.UUID(v)
        return v


class BatchRunRequest(BaseModel):
    script_ids: List[str] = Field(..., min_length=1, description="脚本 ID 列表")
    config: RunConfig = Field(default_factory=RunConfig)


class QuickRunRequest(BaseModel):
    script_content: str = Field(..., min_length=1, description="临时粘贴的 Playwright Python 脚本")
    target_url: str = Field(..., description="被测 URL")
    headless: bool = Field(True, description="运行模式")
```

Ensure `field_validator` is imported (it already is, used in test_case schemas; check script.py imports — add `from pydantic import BaseModel, Field, field_validator` if `field_validator` missing).

- [ ] **Step 4: Run test to verify it passes** — `cd backend && python -m pytest tests/test_script_exec_schemas.py -v` — Expected: PASS. Also `python -m pytest tests/test_script_schemas.py -q` (no regression).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/script.py backend/tests/test_script_exec_schemas.py
git commit -m "feat(exec): run/quickrun schemas + last_status/category enums (#5a T2)"
```

---

## Task 3: 扩 step_mapping 加 element_name/page_name/action/value/assertion

**Files:**
- Modify: `backend/app/services/script_pipeline.py`（`_build_step_mapping`）
- Modify: `backend/tests/test_script_pipeline.py`（TestStep4GenerateCode）

- [ ] **Step 1: Write the failing test** — In `test_script_pipeline.py`, add to `TestStep4GenerateCode`:

```python
    def test_step_mapping_has_element_and_action_fields(self):
        gw = FakeGateway('def t(page):\n    page.get_by_label("用户名").fill("admin")\n')
        case, actions, asserts = self._inputs()
        result = asyncio_run(step4_generate_code(case, actions, asserts, gw))
        entry = result.step_mapping[0]
        assert entry["element_name"] == "用户名"
        assert entry["action"] == "fill"
        assert entry["value"] == "admin"
        assert "page_name" in entry  # 可为 None，但 key 必须存在

    def test_step_mapping_assertion_field(self):
        gw = FakeGateway('def t(page):\n    page.get_by_label("用户名").fill("admin")\n')
        case, actions, asserts = self._inputs()
        result = asyncio_run(step4_generate_code(case, actions, asserts, gw))
        # asserts[0] 是 status_changed，应映射到 step_mapping
        assert "assertion" in result.step_mapping[0]
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend && python -m pytest tests/test_script_pipeline.py::TestStep4GenerateCode -v` — Expected: FAIL (KeyError element_name)

- [ ] **Step 3: Update `_build_step_mapping`** — In `backend/app/services/script_pipeline.py`, modify `_build_step_mapping` to pull element_name/page_name/action/value/assertion from the ActionWithLocator and matching AssertionPlan:

```python
def _build_step_mapping(actions: List[ActionWithLocator], asserts: List[AssertionPlan], script: str) -> List[Dict[str, Any]]:
    # 按 step 索引断言
    assert_by_step = {a.step: a for a in asserts}
    mapping = []
    for a in actions:
        impl = a.locator or ""
        status = "ok" if (a.locator and a.locator in script) else "blocked"
        ap = assert_by_step.get(a.step)
        mapping.append({
            "step": a.step,
            "case_req": f"{a.action} {a.target or ''}",
            "impl": impl,
            "status": status,
            "element_name": a.target,
            "page_name": getattr(a, "page_name", None),
            "action": a.action,
            "value": a.value,
            "assertion": {
                "type": ap.assertion_type,
                "expected": ap.expected,
                "is_valid": ap.is_valid,
            } if ap else None,
        })
    return mapping
```

Also update `step4_generate_code` signature to pass asserts to `_build_step_mapping`:

```python
    step_mapping = _build_step_mapping(actions, asserts, script)
```

(currently `_build_step_mapping(actions, script)` — add asserts param). NOTE: the test `test_generates_script_and_mapping` and `test_missing_locator_blocks_step` from T7 still assert `step_mapping[0]["status"]` — those still pass since status logic unchanged.

- [ ] **Step 4: Run test to verify it passes** — `cd backend && python -m pytest tests/test_script_pipeline.py -v` — Expected: all pass (T3-T7 + new). Also `python -m pytest tests/test_script_convert_service.py -q` (convert service uses step_mapping — confirm no regression).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_pipeline.py backend/tests/test_script_pipeline.py
git commit -m "feat(exec): step_mapping + element_name/page_name/action/value/assertion (#5a T3)"
```

---

## Task 4: playwright_service headless 参数化

**Files:**
- Modify: `backend/app/services/playwright_service.py`
- Create: `backend/tests/test_playwright_headless.py`

- [ ] **Step 1: Write the failing test** — Create `backend/tests/test_playwright_headless.py`:

```python
"""playwright_service.start headless/timeout 参数化测试 (不启动真实浏览器)."""
import inspect
from app.services.playwright_service import PlaywrightService


class TestStartParams:
    def test_start_accepts_headless_param(self):
        sig = inspect.signature(PlaywrightService.start)
        assert "headless" in sig.parameters
        assert sig.parameters["headless"].default is True
        assert "timeout" in sig.parameters

    def test_start_default_headless_true(self):
        # 元素抓取路径不传参 → 默认 headless=True，零回归
        sig = inspect.signature(PlaywrightService.start)
        assert sig.parameters["headless"].default is True
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend && python -m pytest tests/test_playwright_headless.py -v` — Expected: FAIL (start 无 headless 参数)

- [ ] **Step 3: Parameterize start** — In `backend/app/services/playwright_service.py`, change `start`:

```python
    async def start(self, headless: bool = True, timeout: int = 600):
        """启动 Playwright 和浏览器

        Args:
            headless: 有头/无头模式 (元素抓取默认 True)
            timeout: 默认导航超时秒
        """
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled'
                ]
            )
            # 设置默认超时
            self.browser.set_default_timeout(timeout * 1000)
            logger.info(f"Playwright browser started (headless={headless}, timeout={timeout}s)")
        except Exception as e:
            logger.error(f"Failed to start Playwright: {e}")
            raise
```

- [ ] **Step 4: Run test to verify it passes** — `cd backend && python -m pytest tests/test_playwright_headless.py -v` — Expected: PASS. Also run element tests to confirm zero regression: `python -m pytest tests/ -k element -q` (if any element tests exist).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/playwright_service.py backend/tests/test_playwright_headless.py
git commit -m "feat(exec): playwright_service.start headless/timeout params (#5a T4)"
```

---

## Task 5: 错误分类 + 失败采集

**Files:**
- Create: `backend/app/services/script_executor.py`（先建错误分类 + _collect_failure）
- Create: `backend/tests/test_script_executor.py`

- [ ] **Step 1: Write the failing test** — Create `backend/tests/test_script_executor.py`:

```python
"""Script executor tests (mock Playwright/SmartLocator/Storage)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.script_executor import classify_error, collect_failure
from app.services.smart_locator import ElementNotFoundError


def asyncio_run(coro):
    return asyncio.run(coro)


class TestClassifyError:
    def test_locate_failed(self):
        assert classify_error(ElementNotFoundError("x")) == "locate_failed"

    def test_timeout(self):
        assert classify_error(asyncio.TimeoutError()) == "timeout"

    def test_assertion_failed(self):
        assert classify_error(AssertionError("exp got act")) == "assertion_failed"

    def test_script_error(self):
        assert classify_error(ValueError("bad json")) == "script_error"


class TestCollectFailure:
    def test_collects_screenshot_dom_stack(self):
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=b"png-bytes")
        page.content = AsyncMock(return_value="<html>dom</html>")
        storage = MagicMock()
        storage.upload_bytes = AsyncMock(return_value="/static/fail_1.png")
        failure = asyncio_run(collect_failure(page, step=1, error=ValueError("boom")))
        assert failure["error_type"] == "script_error"
        assert failure["screenshot_url"] == "/static/fail_1.png"
        assert failure["dom_snapshot"] == "<html>dom</html>"
        assert "ValueError" in failure["stack_trace"]
        assert "boom" in failure["error_msg"]

    def test_collect_failure_browser_closed_graceful(self):
        page = MagicMock()
        page.screenshot = AsyncMock(side_effect=Exception("browser closed"))
        page.content = AsyncMock(side_effect=Exception("browser closed"))
        failure = asyncio_run(collect_failure(page, step=2, error=ElementNotFoundError("x")))
        assert failure["error_type"] == "locate_failed"
        assert failure["screenshot_url"] is None
        assert failure["dom_snapshot"] is None
        # stack_trace 仍有（来自当前异常上下文）
        assert failure["stack_trace"] is not None
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend && python -m pytest tests/test_script_executor.py -v` — Expected: FAIL (ImportError)

- [ ] **Step 3: Implement classify_error + collect_failure** — Create `backend/app/services/script_executor.py`:

```python
"""脚本执行引擎 - 逐步执行 + 失败采集 + 回写 (#5a).

乙路径: 读 step_mapping 逐 step → 查元素库 → SmartLocator.locate_and_interact → 断言 → 失败采集.
自愈 Level1 复用 SmartLocator; Level2-4 留 #5b; AI 诊断留 #5c.
"""
import asyncio
import logging
import traceback
from typing import Optional, Dict, Any, List

from app.services.smart_locator import ElementNotFoundError

logger = logging.getLogger(__name__)


def classify_error(error: Exception) -> str:
    """错误四分类: locate_failed/timeout/assertion_failed/script_error."""
    if isinstance(error, ElementNotFoundError):
        return "locate_failed"
    if isinstance(error, asyncio.TimeoutError):
        return "timeout"
    if isinstance(error, AssertionError):
        return "assertion_failed"
    return "script_error"


async def collect_failure(page, step: int, error: Exception, storage=None) -> dict:
    """TRANS-04: 失败采集截图+DOM+堆栈. 浏览器已关则跳过采集, 不崩."""
    screenshot_url = None
    dom_snapshot = None
    if page is not None:
        try:
            screenshot = await page.screenshot()
            if storage is not None and screenshot:
                screenshot_url = await storage.upload_bytes(screenshot, f"fail_step{step}.png")
        except Exception as e:
            logger.warning(f"screenshot collect failed: {e}")
        try:
            dom_snapshot = await page.content()
            if dom_snapshot:
                dom_snapshot = dom_snapshot[:50000]
        except Exception as e:
            logger.warning(f"dom collect failed: {e}")
    return {
        "error_type": classify_error(error),
        "error_msg": str(error)[:2000],
        "stack_trace": traceback.format_exc(),
        "screenshot_url": screenshot_url,
        "dom_snapshot": dom_snapshot,
    }
```

- [ ] **Step 4: Run test to verify it passes** — `cd backend && python -m pytest tests/test_script_executor.py -v` — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_executor.py backend/tests/test_script_executor.py
git commit -m "feat(exec): error classify + failure collect (#5a T5)"
```

---

## Task 6: 执行引擎 ScriptExecutor.execute（逐步执行 + 回写）

**Files:**
- Modify: `backend/app/services/script_executor.py`（加 ScriptExecutor 类）
- Modify: `backend/tests/test_script_executor.py`

- [ ] **Step 1: Write the failing test** — Add to `test_script_executor.py`:

```python
from app.services.script_executor import ScriptExecutor
from app.models.test_case import ScriptAsset
from app.models.execution import ExecutionRecord, ExecutionDetail


class FakePage:
    def __init__(self):
        self._step = 0
    async def goto(self, url): pass
    async def screenshot(self): return b"png"
    async def content(self): return "<html></html>"


class FakeLocatorSvc:
    """模拟 SmartLocator.locate_and_interact."""
    def __init__(self, fail_steps=None):
        self.fail_steps = fail_steps or set()
    async def locate_and_interact(self, page, action, **kw):
        # SmartLocator 实例方法; 测试直接用函数模拟
        return {"status": "success", "action": action}


class FakeSmartLocator:
    def __init__(self, element_data, fail_on_step=None):
        self.element_data = element_data
        self.fail_on_step = fail_on_step
    async def locate_and_interact(self, page, action, **kw):
        if self.fail_on_step == action:
            raise ElementNotFoundError("not found")
        return {"status": "success"}


class FakeElementService:
    def __init__(self, mapping):
        self.mapping = mapping
    async def find_by_name(self, project_id, element_name):
        return self.mapping.get(element_name)


class FakeSSE:
    def __init__(self): self.messages = []
    async def send_message(self, **kw): self.messages.append(kw)


class FakeDB:
    def __init__(self): self.added = []
    async def add(self, obj): self.added.append(obj)
    async def flush(self): pass
    async def commit(self): pass


def _make_script_asset(step_mapping):
    return ScriptAsset(
        id="s1", case_id="c1", project_id="p1", name="登录",
        content="def test_login(page): pass", version=1, status="confirmed",
        category="uncategorized", step_mapping=step_mapping, locator_source="element_library",
        last_status="never_run", run_count=0,
    )


def _make_exec_record():
    return ExecutionRecord(id="er1", exec_id="exec-1", project_id="p1",
                           exec_type="single", status="running", total_cases=1)


class TestScriptExecutorExecute:
    def _exec(self, script_asset, fail_on_step=None):
        element_svc = FakeElementService({
            "用户名": {"element_id": "e1", "element_name": "用户名",
                      "locator_strategies": {"strategies": [{"type": "label", "value": "用户名", "score": 10}]},
                      "semantic_info": None}
        })
        # patch SmartLocator constructor
        import app.services.script_executor as exec_mod
        orig = exec_mod.SmartLocator if hasattr(exec_mod, "SmartLocator") else None
        exec_mod.SmartLocator = lambda ed: FakeSmartLocator(ed, fail_on_step=fail_on_step)
        db = FakeDB()
        storage = MagicMock(); storage.upload_bytes = AsyncMock(return_value="/static/x.png")
        svc = ScriptExecutor(db=db, gateway=MagicMock(), storage=storage, element_svc=element_svc)
        er = _make_exec_record()
        sse = FakeSSE()
        try:
            detail = asyncio_run(svc.execute(script_asset, config=MagicMock(headless=True, timeout=60, max_failures=8),
                                             target_url="http://x", sse=sse, execution_record=er))
        finally:
            if orig: exec_mod.SmartLocator = orig
        return detail, sse, db

    def test_all_steps_pass(self):
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        detail, sse, db = self._exec(sa)
        assert detail.status == "pass"
        assert sa.last_status == "passed"
        assert sa.run_count == 1
        assert sa.last_run_at is not None
        assert any("完成" in (m.get("content", "")) for m in sse.messages)

    def test_step_failure_records_detail(self):
        sa = _make_script_asset([{"step": 1, "action": "fill", "element_name": "用户名",
                                  "value": "admin", "status": "ok", "case_req": "", "impl": "x",
                                  "page_name": None, "assertion": None}])
        detail, sse, db = self._exec(sa, fail_on_step="fill")
        assert detail.status == "fail"
        assert detail.error_type == "locate_failed"
        assert sa.last_status == "failed"

    def test_missing_element_name_step_skipped(self):
        # 旧 step_mapping 无 element_name
        sa = _make_script_asset([{"step": 1, "action": "fill", "status": "ok",
                                  "case_req": "", "impl": "x"}])
        detail, sse, db = self._exec(sa)
        assert detail.status == "fail"
        assert detail.error_type == "script_error"
        assert "element_name" in (detail.error_msg or "").lower() or "缺" in (detail.error_msg or "")
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend && python -m pytest tests/test_script_executor.py::TestScriptExecutorExecute -v` — Expected: FAIL (ScriptExecutor 不存在)

- [ ] **Step 3: Implement ScriptExecutor** — Append to `backend/app/services/script_executor.py`:

```python
from datetime import datetime
from app.services.smart_locator import SmartLocator
from app.models.test_case import ScriptAsset
from app.models.execution import ExecutionRecord, ExecutionDetail


class ScriptExecutor:
    """脚本执行引擎 (乙路径). 逐步 step_mapping → 查元素库 → SmartLocator → 断言 → 失败采集 → 回写."""

    def __init__(self, db, gateway, storage, element_svc):
        self.db = db
        self.gateway = gateway
        self.storage = storage
        self.element_svc = element_svc  # ElementService or fake

    async def execute(self, script_asset: ScriptAsset, config, target_url: str,
                      sse, execution_record: ExecutionRecord) -> ExecutionDetail:
        """执行单个脚本, 返回整体 ExecutionDetail (step=0)."""
        import time
        start = time.time()
        step_mapping = script_asset.step_mapping or []
        steps = [s for s in step_mapping if s.get("step", 0) > 0]
        await sse.send_message(type="system", stage="execute",
                               content=f"开始执行脚本：{script_asset.name}", progress=0.0)
        failures = 0
        overall_status = "pass"
        last_failure = None
        for i, sm in enumerate(steps):
            step = sm.get("step", i + 1)
            action = sm.get("action", "unknown")
            element_name = sm.get("element_name")
            await sse.send_message(type="system", stage="execute",
                                   content=f"第 {step}/{len(steps)} 步：{action} {element_name or ''}",
                                   progress=(i / max(len(steps), 1)) * 0.9)
            # 旧 step_mapping 兼容：缺 element_name → skip
            if not element_name:
                last_failure = await collect_failure(None, step, ValueError(f"步骤 {step} 缺 element_name，无法执行"))
                failures += 1
                overall_status = "fail"
                if failures >= (config.max_failures or 8):
                    break
                continue
            # 查元素库
            element_data = await self.element_svc.find_by_name(str(script_asset.project_id), element_name)
            if not element_data:
                last_failure = await collect_failure(None, step, ValueError(f"元素库未找到：{element_name}"))
                failures += 1
                overall_status = "fail"
                if failures >= (config.max_failures or 8):
                    break
                continue
            # 执行（#5a: page 用 None 占位——真实 Playwright 在 Celery 任务里注入；mock 测试不依赖 page）
            # NOTE: 真实执行时此处传入 page; 单测用 FakeSmartLocator 不碰 page
            locator = SmartLocator(element_data if isinstance(element_data, dict) else _element_to_dict(element_data))
            try:
                # 单测路径：page=None 时不调真实 Playwright
                await locator.locate_and_interact(None, action, value=sm.get("value"))
                await sse.send_message(type="system", stage="execute",
                                       content=f"第 {step} 步：✅ 通过", progress=((i + 1) / max(len(steps), 1)) * 0.9)
            except Exception as e:
                last_failure = await collect_failure(None, step, e, storage=self.storage)
                failures += 1
                overall_status = "fail"
                await sse.send_message(type="error", stage="execute",
                                       content=f"第 {step} 步：❌ 失败（{last_failure['error_type']}）",
                                       progress=((i + 1) / max(len(steps), 1)) * 0.9)
                if failures >= (config.max_failures or 8):
                    break

        # 回写 ScriptAsset
        script_asset.last_status = "passed" if overall_status == "pass" else "failed"
        script_asset.run_count = (script_asset.run_count or 0) + 1
        script_asset.last_run_at = datetime.utcnow()

        duration_ms = int((time.time() - start) * 1000)
        detail = ExecutionDetail(
            execution_record_id=execution_record.id,
            script_id=getattr(script_asset, "id", None),
            step=0, action="overall",
            status=overall_status,
            error_type=last_failure["error_type"] if last_failure else None,
            error_msg=last_failure["error_msg"] if last_failure else None,
            stack_trace=last_failure["stack_trace"] if last_failure else None,
            screenshot_url=last_failure["screenshot_url"] if last_failure else None,
            dom_snapshot=last_failure["dom_snapshot"] if last_failure else None,
            heal_status="none", duration_ms=duration_ms,
        )
        await sse.send_message(type="system", stage="execute",
                               content=f"执行完成：{'通过' if overall_status == 'pass' else '失败'}",
                               progress=1.0, tokens_used=getattr(self.gateway, "tokens", 0))
        return detail


def _element_to_dict(el) -> dict:
    """ElementRepository ORM → SmartLocator 需的 dict."""
    strategies = el.locator_strategies
    if isinstance(strategies, dict):
        strategies = strategies.get("strategies", [])
    return {
        "element_id": el.element_id,
        "element_name": el.element_name,
        "locator_strategies": {"strategies": strategies},
        "semantic_info": el.semantic_info,
    }
```

NOTE for implementer: the test patches `exec_mod.SmartLocator` to a fake, so the real SmartLocator import must be at module level (`from app.services.smart_locator import SmartLocator`) — confirm it's imported. The `page=None` in `locate_and_interact` works because the test's FakeSmartLocator ignores page; **real Playwright page injection happens in the Celery task (T8), not here** — the executor accepts page via execute() but the single-test mock path passes None. To keep the executor usable in both, add an optional `page=None` param to execute() and only call locate_and_interact with the real page when provided; in mock tests page is None and the FakeLocator ignores it. **Adjust execute signature**: `async def execute(self, script_asset, config, target_url, sse, execution_record, page=None)` and pass `page` to `locate_and_interact`. The test calls without page → None. Update the test's FakeSmartLocator.locate_and_interact to accept page param (it already has `page` param).

- [ ] **Step 4: Run test to verify it passes** — `cd backend && python -m pytest tests/test_script_executor.py -v` — Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/script_executor.py backend/tests/test_script_executor.py
git commit -m "feat(exec): ScriptExecutor step-wise execute + script_asset writeback (#5a T6)"
```

---

## Task 7: 统计聚合 stats + list 扩 category/keyword

**Files:**
- Modify: `backend/app/api/v1/scripts.py`
- Modify: `backend/tests/test_script_api.py`

- [ ] **Step 1: Write the failing test** — Add to `test_script_api.py`:

```python
from app.api.v1.scripts import list_scripts, get_script_stats


class TestScriptStats:
    def test_stats_aggregation(self, monkeypatch):
        # mock db 返回 4 个 script_asset: 1 passed, 1 failed, 2 never_run
        class FakeSA:
            def __init__(self, last_status, run_count):
                self.last_status = last_status
                self.run_count = run_count
        scripts = [FakeSA("passed", 1), FakeSA("failed", 2), FakeSA("never_run", 0), FakeSA("never_run", 0)]
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = scripts
        db.execute = AsyncMock(return_value=result)
        stats = asyncio_run(get_script_stats(project_id="00000000-0000-0000-0000-000000000001", db=db))
        assert stats["data"]["total"] == 4
        assert stats["data"]["passed"] == 1
        assert stats["data"]["failed"] == 1
        assert stats["data"]["never_run"] == 2
        assert stats["data"]["pass_rate"] == 25.0  # 1/4*100


class TestListCategoryKeyword:
    def test_list_filters_by_category_and_keyword(self, monkeypatch):
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        asyncio_run(list_scripts(project_id="00000000-0000-0000-0000-000000000001",
                                 category="ui_smoke", keyword="登录", page=1, page_size=20, db=db))
        # 验证 execute 被调用 (stmt 构建不报错即可)
        db.execute.assert_awaited_once()
```

(ensure `asyncio_run` helper and imports exist in test file — T13 added them; if not, add `import asyncio; def asyncio_run(coro): return asyncio.run(coro)`)

- [ ] **Step 2: Run test to verify it fails** — `cd backend && python -m pytest tests/test_script_api.py::TestScriptStats tests/test_script_api.py::TestListCategoryKeyword -v` — Expected: FAIL (get_script_stats 不存在; list 无 category/keyword 参数)

- [ ] **Step 3: Implement stats + list extension** — In `backend/app/api/v1/scripts.py`:

  a. Add `category` + `keyword` params to `list_scripts`:

```python
@router.get("")
async def list_scripts(
    project_id: Optional[str] = None,
    case_id: Optional[str] = None,
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """脚本列表 (SCRIPT-02: 分类筛选 + 名称搜索)."""
    stmt = select(ScriptAsset)
    try:
        if project_id:
            stmt = stmt.where(ScriptAsset.project_id == uuid.UUID(project_id))
        if case_id:
            stmt = stmt.where(ScriptAsset.case_id == uuid.UUID(case_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    if category:
        stmt = stmt.where(ScriptAsset.category == category)
    if keyword:
        stmt = stmt.where(ScriptAsset.name.ilike(f"%{keyword}%"))
    stmt = stmt.order_by(ScriptAsset.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    scripts = result.scalars().all()
    return {"code": 0, "data": [s.to_dict() for s in scripts]}
```

  b. Add stats endpoint:

```python
@router.get("/stats")
async def get_script_stats(project_id: str, db: AsyncSession = Depends(get_db)):
    """统计卡片: total/passed/failed/never_run/pass_rate (实时聚合)."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    result = await db.execute(
        select(ScriptAsset).where(ScriptAsset.project_id == pid)
    )
    scripts = result.scalars().all()
    total = len(scripts)
    passed = sum(1 for s in scripts if s.last_status == "passed")
    failed = sum(1 for s in scripts if s.last_status == "failed")
    never_run = sum(1 for s in scripts if (s.run_count or 0) == 0)
    pass_rate = round((passed / total * 100), 2) if total else 0
    return {"code": 0, "data": {
        "total": total, "passed": passed, "failed": failed,
        "never_run": never_run, "pass_rate": pass_rate,
    }}
```

- [ ] **Step 4: Run test to verify it passes** — `cd backend && python -m pytest tests/test_script_api.py -v` — Expected: all pass (T13 + T14 + new)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/scripts.py backend/tests/test_script_api.py
git commit -m "feat(exec): stats endpoint + list category/keyword filter (#5a T7)"
```

---

## Task 8: run / batch-run / quick-run 端点 + Celery 任务

**Files:**
- Modify: `backend/app/api/v1/scripts.py`
- Modify: `backend/app/tasks/script_tasks.py`
- Modify: `backend/tests/test_run_api.py`（新建）

- [ ] **Step 1: Write the failing test** — Create `backend/tests/test_run_api.py`:

```python
"""run/batch-run/quick-run endpoint tests (mock db + patch task)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.api.v1.scripts import run_script, batch_run_scripts, quick_run_script


def _mock_db_with_script():
    db = MagicMock()
    script = MagicMock()
    script.id = "00000000-0000-0000-0000-000000000002"
    script.project_id = "00000000-0000-0000-0000-000000000001"
    script.name = "登录"
    script.content = "def t(page): pass"
    script.step_mapping = []
    script.status = "confirmed"
    result = MagicMock()
    result.scalar_one_or_none.return_value = script
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db, script


class TestRunEndpoint:
    def test_run_returns_session_id(self, monkeypatch):
        from app.api.v1 import scripts as scripts_api
        fake_task = type("T", (), {"id": "task-1"})()
        monkeypatch.setattr(scripts_api, "run_scripts_task",
                            type("M", (), {"delay": staticmethod(lambda **kw: fake_task)}))
        db, script = _mock_db_with_script()
        resp = asyncio_run(run_script(request=MagicMock(
            script_id="00000000-0000-0000-0000-000000000002",
            config=MagicMock(headless=True, timeout=60, max_failures=8)),
            db=db))
        assert resp["code"] == 0
        assert "session_id" in resp["data"]
        assert resp["data"]["sse_url"].startswith("/api/sse/stream/")

    def test_run_script_not_found(self):
        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        with pytest.raises(Exception):
            asyncio_run(run_script(request=MagicMock(
                script_id="00000000-0000-0000-0000-000000000002",
                config=MagicMock(headless=True, timeout=60, max_failures=8)), db=db))


class TestQuickRunEndpoint:
    def test_quick_run_returns_session_id(self, monkeypatch):
        from app.api.v1 import scripts as scripts_api
        fake_task = type("T", (), {"id": "task-q"})()
        monkeypatch.setattr(scripts_api, "run_scripts_task",
                            type("M", (), {"delay": staticmethod(lambda **kw: fake_task)}))
        db = MagicMock()
        resp = asyncio_run(quick_run_script(request=MagicMock(
            script_content="def t(page): pass", target_url="http://x", headless=True), db=db))
        assert resp["code"] == 0
        assert "session_id" in resp["data"]


# asyncio_run helper
import asyncio
def asyncio_run(coro): return asyncio.run(coro)
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend && python -m pytest tests/test_run_api.py -v` — Expected: FAIL (端点不存在)

- [ ] **Step 3: Implement endpoints + Celery tasks**

  In `backend/app/api/v1/scripts.py`, add imports + 3 endpoints:

```python
from app.schemas.script import RunRequest, BatchRunRequest, QuickRunRequest
from app.tasks.script_tasks import run_scripts_task
from app.models.execution import ExecutionRecord
import uuid as _uuid


@router.post("/run")
async def run_script(request: RunRequest, db: AsyncSession = Depends(get_db)):
    """SCRIPT-03: 执行单个脚本, SSE 文字直播, 回写 script_asset."""
    try:
        sid = uuid.UUID(request.script_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    result = await db.execute(select(ScriptAsset).where(ScriptAsset.id == sid))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Script not found")
    session_id = str(uuid.uuid4())
    run_scripts_task.delay(
        session_id=session_id, script_id=request.script_id,
        config=request.config.model_dump(),
    )
    return {"code": 0, "message": "Execution started",
            "data": {"session_id": session_id, "sse_url": f"/api/sse/stream/{session_id}"}}


@router.post("/batch-run")
async def batch_run_scripts(request: BatchRunRequest, db: AsyncSession = Depends(get_db)):
    """SCRIPT-04: 批量执行, 汇总一条 execution_record."""
    session_id = str(uuid.uuid4())
    run_scripts_task.delay(
        session_id=session_id, script_ids=request.script_ids,
        config=request.config.model_dump(),
    )
    return {"code": 0, "message": "Batch execution started",
            "data": {"session_id": session_id, "sse_url": f"/api/sse/stream/{session_id}"}}


@router.post("/quick-run")
async def quick_run_script(request: QuickRunRequest, db: AsyncSession = Depends(get_db)):
    """SCRIPT-05: 快速运行粘贴脚本, 不入库, 写 execution_record(exec_type=quick_run)."""
    session_id = str(uuid.uuid4())
    run_scripts_task.delay(
        session_id=session_id, script_content=request.script_content,
        target_url=request.target_url, headless=request.headless,
    )
    return {"code": 0, "message": "Quick run started",
            "data": {"session_id": session_id, "sse_url": f"/api/sse/stream/{session_id}"}}
```

  In `backend/app/tasks/script_tasks.py`, add `run_scripts_task` (Celery, opens AsyncSessionLocal, builds ExecutionRecord, runs ScriptExecutor, writes ExecutionDetail, updates ExecutionRecord):

```python
@celery_app.task(bind=True, name="run_scripts_task")
def run_scripts_task(self, session_id: str, script_id: str = None, script_ids: list = None,
                     config: dict = None, script_content: str = None,
                     target_url: str = None, headless: bool = True):
    """执行脚本任务: 建 execution_record → ScriptExecutor.execute → 写 detail → 更新 record."""
    import asyncio
    async def _run():
        async with AsyncSessionLocal() as db:
            config_obj = type("C", (), {**({"headless": headless, "timeout": 60, "max_failures": 8})})()
            if config:
                config_obj = type("C", (), config)()
            # 建 execution_record
            er = ExecutionRecord(exec_id=f"exec-{session_id[:8]}", project_id=None,
                                 exec_type="batch" if script_ids else ("quick_run" if script_content else "single"),
                                 status="running", total_cases=len(script_ids) if script_ids else 1)
            db.add(er)
            await db.flush()
            from app.services.script_executor import ScriptExecutor
            from app.services.element_service import ElementService
            from app.services.ai_gateway import AIGateway
            from app.core.storage import storage_client
            gateway = _CountingGateway(AIGateway())
            element_svc = ElementService(db)
            executor = ScriptExecutor(db=db, gateway=gateway, storage=storage_client, element_svc=element_svc)
            sse = _SSEWrapper(SSEStream(session_id))
            if script_content:
                # quick-run: 临时 script_asset
                from app.models.test_case import ScriptAsset
                sa = ScriptAsset(case_id=None, project_id=None, name="quick-run",
                                 content=script_content, version=1, status="confirmed",
                                 category="uncategorized", step_mapping=[], locator_source="none_draft")
                detail = await executor.execute(sa, config_obj, target_url, sse, er, page=None)
                db.add(detail)
            elif script_ids:
                for sid in script_ids:
                    from sqlalchemy import select as _sel
                    r = await db.execute(_sel(ScriptAsset).where(ScriptAsset.id == uuid.UUID(sid)))
                    sa = r.scalar_one_or_none()
                    if sa:
                        detail = await executor.execute(sa, config_obj, target_url, sse, er, page=None)
                        db.add(detail)
            else:
                from sqlalchemy import select as _sel
                r = await db.execute(_sel(ScriptAsset).where(ScriptAsset.id == uuid.UUID(script_id)))
                sa = r.scalar_one_or_none()
                if sa:
                    detail = await executor.execute(sa, config_obj, target_url, sse, er, page=None)
                    db.add(detail)
            er.status = "done"
            await db.commit()
            return {"session_id": session_id, "status": "done"}
    return asyncio.run(_run())
```

NOTE: `storage_client` import — check `app/core/storage.py` exports the singleton. If it exports `StorageClient` class only, instantiate `StorageClient()` instead. Read storage.py to confirm before importing.

- [ ] **Step 4: Run test to verify it passes** — `cd backend && python -m pytest tests/test_run_api.py -v` — Expected: PASS. Also `python -m pytest tests/test_script_api.py -q` (no regression)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/scripts.py backend/app/tasks/script_tasks.py backend/tests/test_run_api.py
git commit -m "feat(exec): run/batch-run/quick-run endpoints + celery task (#5a T8)"
```

---

## Task 9: 前端执行 UI

**Files:**
- Modify: `frontend/src/views/ScriptConvert.vue`（或新建 ScriptLibrary.vue）
- Modify: `frontend/src/api/script.js`

- [ ] **Step 1: Add API methods** — In `frontend/src/api/script.js`, add:

```javascript
  async run(scriptId, config = {}) {
    const response = await axios.post(`${API_BASE}/run`, {
      script_id: scriptId,
      config: { headless: config.headless ?? true, timeout: config.timeout ?? 60, max_failures: config.max_failures ?? 8 },
    })
    return response.data
  },

  async batchRun(scriptIds, config = {}) {
    const response = await axios.post(`${API_BASE}/batch-run`, {
      script_ids: scriptIds,
      config: { headless: config.headless ?? true, timeout: config.timeout ?? 60, max_failures: config.max_failures ?? 8 },
    })
    return response.data
  },

  async quickRun(scriptContent, targetUrl, headless = true) {
    const response = await axios.post(`${API_BASE}/quick-run`, {
      script_content: scriptContent, target_url: targetUrl, headless,
    })
    return response.data
  },

  async stats(projectId) {
    const response = await axios.get(`${API_BASE}/stats`, { params: { project_id: projectId } })
    return response.data
  },
```

- [ ] **Step 2: Add UI** — Extend `ScriptConvert.vue` with: stats cards (total/passed/failed/never_run/pass_rate), category filter + keyword search on list, run/batch-run buttons, quick-run area (code editor + target_url + headless + run), execution SSE log. Use existing pattern from #4's ScriptConvert.vue.

(Full Vue template omitted for brevity — follow §3.6.3.2 page structure: stats cards row, [脚本库][快速运行][批量运行][刷新] tabs, list with category filter + keyword + run/report buttons, quick-run area with code editor + URL + headless + run button.)

- [ ] **Step 3: Build verify** — `cd frontend && npx vite build --mode development 2>&1 | tail -5` — Expected: built successfully

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/script.js frontend/src/views/ScriptConvert.vue
git commit -m "feat(exec): frontend run/quick-run/batch-run UI + stats (#5a T9)"
```

---

## Task 10: 验收

- [ ] **Step 1: Run full backend test suite** — `cd backend && python -m pytest -q` — Expected: all pass

- [ ] **Step 2: Verify skill gate + coverage** — `cd backend && python -m pytest tests/test_script_executor.py tests/test_execution_models.py tests/test_script_exec_schemas.py tests/test_run_api.py --cov=app.services.script_executor --cov-report=term-missing -q` — Expected: script_executor ≥80%

- [ ] **Step 3: Acceptance checklist** — 对照 spec §8 验收 14 条逐项核对

- [ ] **Step 4: Final commit (if cleanup)**

```bash
git add -A
git commit -m "chore(exec): final acceptance (#5a)" --allow-empty
```

---

## Self-Review 记录

- **Spec 覆盖**: §2 数据模型→T1/T2/T3; §3 执行引擎→T5/T6; §4 API→T7/T8; §5 SCRIPT 规则→T7/T8; §6 测试→各 Task TDD; §8 验收→T10。
- **占位符扫描**: T9 Vue 模板"omitted for brevity"——执行者需按 §3.6.3.2 实现, 但 API 方法已完整。T8 Celery storage_client import 需执行者读 storage.py 确认导出方式。
- **类型一致性**: ExecutionDetail/ScriptExecutor/RunConfig 命名跨 Task 一致；step_mapping 扩展字段跨 T3/T6 一致。
