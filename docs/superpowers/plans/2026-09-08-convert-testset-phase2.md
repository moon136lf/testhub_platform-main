# 阶段2：转脚本+测试集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 转脚本页改造（页面树勾选+转换弹窗SSE+步骤化脚本编辑器）、测试集模型与执行链路、UI自动化测试页（测试集列表/执行配置/SSE直播/报告含失败截图）、用例可自动化评级——"不懂代码也能看/改脚本"的用户核心诉求落地。

**Architecture:** 新建 `test_set` 模型（name/source/case_ids JSONB/last_run/pass_rate/status）承载执行规划层；步骤化编辑器走「行式步骤存储 → 后端 codegen 生成 Playwright 脚本」链路（复用 script_pipeline 的 ActionIntent 词汇表）；执行复用现有 run_scripts_task + ScriptExecutor（失败截图已入 MinIO + execution_detail.screenshot_url，本阶段打通到测试集报告展示）。前端 ScriptConvert.vue 改造 + 新建 AutoUITest.vue。

**Tech Stack:** 同阶段1（FastAPI + SQLAlchemy async + Vue3 + Element Plus）；测试 mock 风格；基线 658 passed（master 已含阶段1）。

**需求依据:** docs/SESSION_HANDOFF_2026-09-04-refactor-plan.md 阶段2 行 + 功能决策明细；千问原型 scripts section（测试集双Tab/报告drawer）。

**前置事实（已核实）:**
- ScriptAsset.step_mapping 每项含 {step, case_req, impl, status, element_name, action, value, assertion}——**步骤化编辑器的数据基础已存在**
- 脚本转链路：step0_normalize→step1_to_actions→step2_to_assertions→step3_match_locators→step4_generate_code（script_pipeline.py）
- 失败截图：script_executor.py 已存 MinIO + execution_detail.screenshot_url（§4 明细表）——只差报告 UI 内嵌
- 执行入口：POST /scripts/run（单）/batch-run（批量），run_scripts_task.delay(script_ids, config, exec_type)
- ExecutionRecord: exec_id/exec_type/status/total/passed/fail/pass_rate/duration_ms；ExecutionDetail: 每用例结果+error_type+screenshot_url
- convert 端点已校验 is_finalized；SSE 复用 /api/sse/stream/{session_id}
- **阶段1 遗留约束：fallback 消费端以 verified 标志做质量判断（reorder 压平 score 差距）**——本阶段编辑器生成脚本时沿用
- 前端路由：/ai/convert（ScriptConvert.vue 当前双Tab：转脚本/脚本库执行）；UI自动化测试页路由 /auto/ui 当前 redirect 到 /ai/convert——本阶段拆开

---

## File Structure

| 文件 | 职责 |
|---|---|
| `backend/migrations/014_test_sets.sql` | 幂等 DDL：test_set 表 |
| `backend/app/models/test_set.py` | TestSet 模型 + to_dict |
| `backend/app/models/__init__.py` | 注册 TestSet |
| `backend/app/services/test_set_service.py` | 测试集 CRUD + 执行编排 + 报告聚合 |
| `backend/app/services/step_codegen.py` | 新建：行式步骤 → Playwright 代码生成（编辑器后端） |
| `backend/app/api/v1/test_sets.py` | 测试集端点（CRUD/执行/报告） |
| `backend/app/api/__init__.py` | 注册 test_sets router |
| `backend/app/api/v1/scripts.py` | 追加脚本内容更新端点（编辑器保存）+ 步骤模板端点 |
| `backend/app/api/v1/test_cases.py` | 追加可自动化评级字段透出（feasibility_level 已有列，确认 to_dict） |
| `frontend/src/views/ScriptConvert.vue` | 改造：页面树勾选 + 转换弹窗SSE + 存为测试集 + 脚本编辑入口 |
| `frontend/src/components/StepEditor.vue` | 新建：步骤化编辑器（行式动作+AI生成SQL按钮） |
| `frontend/src/views/AutoUITest.vue` | 新建：UI自动化测试页（测试集Tab+脚本库Tab） |
| `frontend/src/api/testSet.js` | 新建 API 封装 |

---

### Task 0: 测试集模型 + 迁移

**Files:**
- Create: `backend/migrations/014_test_sets.sql`
- Create: `backend/app/models/test_set.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_test_set_models.py`

- [ ] **Step 1: 迁移 SQL（幂等）**

```sql
-- Migration: test_set table (phase2 execution planning layer)
-- Idempotent.

CREATE TABLE IF NOT EXISTS test_set (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',  -- manual/ai_suggest/convert_page
    case_ids JSONB NOT NULL DEFAULT '[]',          -- [test_case.id]
    description VARCHAR(500),
    last_run_at TIMESTAMPTZ,
    last_pass_rate NUMERIC(5,2) DEFAULT 0,
    last_exec_id VARCHAR(50),                      -- 关联 execution_record.exec_id
    status VARCHAR(20) DEFAULT 'pending',          -- pending/running/done
    created_by VARCHAR(50) DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_test_set_project_name UNIQUE (project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_test_set_project ON test_set(project_id);
```

- [ ] **Step 2: 失败测试**

```python
"""TestSet 模型测试（字段存在性 + to_dict）"""
from app.models.test_set import TestSet


class TestTestSetModel:
    def test_fields_exist(self):
        ts = TestSet()
        for f in ("name", "source", "case_ids", "last_pass_rate", "last_exec_id", "status"):
            assert hasattr(ts, f)

    def test_to_dict_shape(self):
        ts = TestSet(name="冒烟集", source="manual", case_ids=["a", "b"], status="pending")
        d = ts.to_dict()
        assert d["name"] == "冒烟集"
        assert d["case_ids"] == ["a", "b"]
        assert d["source"] == "manual"
```

- [ ] **Step 3: 实现**

```python
"""Test set model — 阶段2 执行规划层（用例勾选集，来源 manual/ai_suggest/convert_page）"""
import uuid
from sqlalchemy import Column, String, Integer, Numeric, ForeignKey, UniqueConstraint, Index, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class TestSet(Base):
    """测试集"""
    __tablename__ = "test_set"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_set_project_name"),
        Index("idx_test_set_project", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    source = Column(String(20), nullable=False, default="manual")  # manual/ai_suggest/convert_page
    case_ids = Column(JSONB, nullable=False, default=list)
    description = Column(String(500))
    last_run_at = Column(DateTime(timezone=True))
    last_pass_rate = Column(Numeric(5, 2), default=0)
    last_exec_id = Column(String(50))
    status = Column(String(20), default="pending")  # pending/running/done
    created_by = Column(String(50), default="system")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "name": self.name,
            "source": self.source,
            "case_ids": self.case_ids or [],
            "description": self.description,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_pass_rate": float(self.last_pass_rate or 0),
            "last_exec_id": self.last_exec_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
```

`models/__init__.py` 加 `from app.models.test_set import TestSet`。

- [ ] **Step 4: 测试过 + 执行迁移到真实库（try/except 逐条，参照 013 方式）**
- [ ] **Step 5: Commit** `feat(testset): test_set model + migration`

---

### Task 1: 步骤代码生成器（编辑器后端核心）

**Files:**
- Create: `backend/app/services/step_codegen.py`
- Test: `backend/tests/test_step_codegen.py`

- [ ] **Step 1: 失败测试**

```python
"""步骤化编辑器 → Playwright 代码生成。
操作类型词表 = 转脚本 ActionIntent 词表 + assert_db 数据库断言。"""
import pytest
from app.services.step_codegen import generate_script, SUPPORTED_ACTIONS


class TestCodegen:
    def test_generate_navigate_and_click(self):
        steps = [
            {"seq": 1, "action": "navigate", "target": "", "value": "https://x.com/login",
             "element_name": ""},
            {"seq": 2, "action": "click", "target": "#login-btn", "value": "", "element_name": "登录按钮"},
        ]
        code = generate_script("登录用例", steps)
        assert "page.goto(\"https://x.com/login\")" in code
        assert 'page.locator("#login-btn").click()' in code

    def test_input_with_value(self):
        steps = [{"seq": 1, "action": "input", "target": "#user", "value": "admin", "element_name": "用户名"}]
        code = generate_script("t", steps)
        assert 'page.locator("#user").fill("admin")' in code

    def test_wait_seconds(self):
        steps = [{"seq": 1, "action": "wait", "target": "", "value": "2", "element_name": ""}]
        code = generate_script("t", steps)
        assert "page.wait_for_timeout(2000)" in code

    def test_assert_text(self):
        steps = [{"seq": 1, "action": "assert_text", "target": ".title", "value": "仪表盘", "element_name": "标题"}]
        code = generate_script("t", steps)
        assert 'expect(page.locator(".title")).to_have_text("仪表盘")' in code

    def test_assert_db_generates_query_block(self):
        steps = [{"seq": 1, "action": "assert_db", "target": "",
                  "value": "SELECT count(*) FROM test_case", "element_name": "用例数",
                  "expected": "5"}]
        code = generate_script("t", steps)
        assert "assert_db" in code
        assert "SELECT count(*) FROM test_case" in code
        assert '"5"' in code or "'5'" in code

    def test_select_action(self):
        steps = [{"seq": 1, "action": "select", "target": "#env", "value": "dev", "element_name": "环境"}]
        code = generate_script("t", steps)
        assert 'select_option("dev")' in code

    def test_empty_steps_raises(self):
        with pytest.raises(ValueError):
            generate_script("t", [])

    def test_unknown_action_raises(self):
        with pytest.raises(ValueError, match="不支持"):
            generate_script("t", [{"seq": 1, "action": "hack", "target": "", "value": ""}])

    def test_header_has_imports(self):
        code = generate_script("t", [{"seq": 1, "action": "wait", "target": "", "value": "1"}])
        assert "from playwright.sync_api" in code and "expect" in code

    def test_supported_actions_exported(self):
        # 前端下拉数据源契约
        assert "navigate" in SUPPORTED_ACTIONS and "assert_db" in SUPPORTED_ACTIONS
```

- [ ] **Step 2: 实现**

```python
"""步骤化编辑器 → Playwright 代码生成（阶段2 核心件）。

行式步骤存储（每行 = seq/action/target/value/element_name/expected），
codegen 把它转成可执行的 Playwright 同步脚本。操作词表与转脚本链路
ActionIntent 对齐，扩展 assert_db 数据库断言（SQL+期望值）。"""
from typing import Dict, List

SUPPORTED_ACTIONS = [
    "navigate", "click", "input", "select", "wait",
    "assert_text", "assert_visible", "assert_db",
]

_HEADER = '''"""{title} — 由步骤化编辑器生成"""
from playwright.sync_api import sync_playwright, expect

def run(page):
'''


def _escape(v: str) -> str:
    return (v or "").replace("\\", "\\\\").replace('"', '\\"')


def _gen_step(step: Dict) -> str:
    action = step.get("action", "")
    target = step.get("target", "")
    value = step.get("value", "")
    loc = f'page.locator("{_escape(target)}")' if target else None

    if action == "navigate":
        return f'    page.goto("{_escape(value)}")'
    if action == "click":
        if not loc:
            raise ValueError("click 需要 target")
        return f"    {loc}.click()"
    if action == "input":
        if not loc:
            raise ValueError("input 需要 target")
        return f'    {loc}.fill("{_escape(value)}")'
    if action == "select":
        if not loc:
            raise ValueError("select 需要 target")
        return f'    {loc}.select_option("{_escape(value)}")'
    if action == "wait":
        try:
            ms = int(float(value or 1) * 1000)
        except ValueError:
            ms = 1000
        return f"    page.wait_for_timeout({ms})"
    if action == "assert_text":
        if not loc:
            raise ValueError("assert_text 需要 target")
        return f'    expect({loc}).to_have_text("{_escape(value)}")'
    if action == "assert_visible":
        if not loc:
            raise ValueError("assert_visible 需要 target")
        return f"    expect({loc}).to_be_visible()"
    if action == "assert_db":
        sql = _escape(step.get("value", ""))
        expected = _escape(step.get("expected", ""))
        # 平台内执行：step_runner 支持的伪调用，执行时由 runner 拦截跑 SQL
        return (f'    assert_db(page, sql="{sql}", expected="{expected}", '
                f'name="{_escape(step.get("element_name", ""))}")  # DB断言')
    raise ValueError(f"不支持的操作类型: {action}")


def generate_script(title: str, steps: List[Dict]) -> str:
    """行式步骤 → Playwright 脚本文本。步骤空/操作未知抛 ValueError。"""
    if not steps:
        raise ValueError("至少需要一个步骤")
    body = []
    for s in sorted(steps, key=lambda x: x.get("seq", 0)):
        body.append(_gen_step(s))
    return _HEADER.format(title=_escape(title)) + "\n".join(body) + "\n"
```

（assert_db 的执行语义：脚本运行时 runner 提供 assert_db 全局函数——在 script_executor 的执行上下文注入；本任务只管生成，执行注入在 Task 4。）

- [ ] **Step 3: 测试过 + 全量回归**
- [ ] **Step 4: Commit** `feat(script): step-based codegen — editor rows to Playwright with assert_db`

---

### Task 2: 脚本内容保存端点 + 步骤模板

**Files:**
- Modify: `backend/app/api/v1/scripts.py`
- Test: `backend/tests/test_api_script_edit.py`

- [ ] **Step 1: 失败测试**（TestClient 风格参照 test_api_elements.py 的 mock db 模式）

```python
"""脚本编辑保存端点：PUT /scripts/{id}/content（步骤化编辑器保存）"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4


class TestScriptContentUpdate:
    @pytest.mark.asyncio
    async def test_save_steps_generates_content(self):
        """保存行式步骤 → codegen 生成脚本 → 写 ScriptAsset.content + steps JSONB + version+1"""
        # mock db.get 返回 ScriptAsset magic
        # 调 service 更新后断言 content 含生成的 playwright 代码、steps 被存
        ...

    @pytest.mark.asyncio
    async def test_save_rejects_empty_steps(self):
        ...  # 400
```

（实现时补全 mock 细节，参照 test_element_asset_service 模式。）

- [ ] **Step 2: 实现**

service 层（可放 script_convert_service 或新 script_edit_service，实现者选——建议新 `script_edit_service.py`）：

```python
class ScriptEditService:
    async def save_steps(self, script_id: str, title: str, steps: List[Dict]) -> ScriptAsset:
        """保存步骤化编辑：codegen 生成脚本 + 存原始步骤 + version+1。"""
        asset = await self.db.get(ScriptAsset, UUID(script_id))
        if not asset:
            raise ValueError("脚本不存在")
        if not steps:
            raise ValueError("至少需要一个步骤")
        content = generate_script(title or asset.name, steps)
        asset.content = content
        asset.step_mapping = steps  # 编辑器行存回 step_mapping（复用字段）
        asset.version = (asset.version or 1) + 1
        await self.db.commit()
        return asset
```

API：`PUT /scripts/{script_id}/content` body `{title?, steps: [...]}` → data: asset.to_dict()。

- [ ] **Step 3: 测试过 + Commit** `feat(script): save steps endpoint — editor persists via codegen`

---

### Task 3: 测试集 CRUD + 存为测试集

**Files:**
- Create: `backend/app/services/test_set_service.py`
- Create: `backend/app/api/v1/test_sets.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_test_set_service.py`

- [ ] **Step 1: 失败测试**

```python
"""TestSetService 测试（mock db）"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4

from app.services.test_set_service import TestSetService


def _db():
    return MagicMock()


class TestCrud:
    @pytest.mark.asyncio
    async def test_create_with_case_ids(self):
        db = _db()
        added = []
        db.add = lambda o: added.append(o)
        db.commit = AsyncMock()
        db.flush = AsyncMock()

        svc = TestSetService(db)
        ts = await svc.create_set("p1", "冒烟集", ["c1", "c2"], source="convert_page")
        assert added[0].name == "冒烟集"
        assert added[0].case_ids == ["c1", "c2"]
        assert added[0].source == "convert_page"

    @pytest.mark.asyncio
    async def test_create_empty_name_raises(self):
        svc = TestSetService(_db())
        with pytest.raises(ValueError):
            await svc.create_set("p1", "  ", ["c1"])

    @pytest.mark.asyncio
    async def test_create_empty_cases_raises(self):
        svc = TestSetService(_db())
        with pytest.raises(ValueError):
            await svc.create_set("p1", "x", [])

    @pytest.mark.asyncio
    async def test_add_cases_merges(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1"]

        async def _get(cls, sid):
            return ts
        db.get = _get
        db.commit = AsyncMock()

        svc = TestSetService(db)
        await svc.add_cases(str(uuid4()), ["c2", "c1"])  # c1 重复不进
        assert sorted(ts.case_ids) == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_remove_case(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1", "c2"]

        async def _get(cls, sid):
            return ts
        db.get = _get
        db.commit = AsyncMock()

        svc = TestSetService(db)
        await svc.remove_case(str(uuid4()), "c1")
        assert ts.case_ids == ["c2"]

    @pytest.mark.asyncio
    async def test_list_by_project(self):
        db = _db()
        rows = [MagicMock(), MagicMock()]
        db.execute = _exec(rows)
        svc = TestSetService(db)
        assert len(await svc.list_sets("p1")) == 2


def _exec(rows):
    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        return r
    return _execute
```

- [ ] **Step 2: 实现**（模式同 element_asset_service：ValueError → 400、_to_uuid 辅助）

API 端点（`test_sets.py`，挂 `/test-sets`）：
- `GET /test-sets?project_id=` 列表
- `POST /test-sets` {project_id, name, case_ids, source, description}
- `PUT /test-sets/{id}` {name?, description?}
- `DELETE /test-sets/{id}`
- `POST /test-sets/{id}/cases` {case_ids}（合并去重）
- `DELETE /test-sets/{id}/cases/{case_id}`

`api/__init__.py` 注册（无前缀，路径自带 test-sets）。

- [ ] **Step 3: 测试过 + Commit** `feat(testset): CRUD + case management`

---

### Task 4: 测试集执行 + 报告聚合

**Files:**
- Modify: `backend/app/services/test_set_service.py`（执行编排）
- Modify: `backend/app/api/v1/test_sets.py`
- Test: `backend/tests/test_test_set_service.py`（追加）

- [ ] **Step 1: 失败测试**

```python
class TestExecution:
    @pytest.mark.asyncio
    async def test_run_resolves_cases_to_scripts(self):
        """执行测试集：case_ids → 查 script_asset → 取 script_ids → run_scripts_task.delay"""
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1", "c2"]
        ts.name = "冒烟集"

        async def _get(cls, sid):
            return ts
        # 查脚本：返回两条 script（每 case 一条，取最新）
        script_rows = [MagicMock(id=uuid4()), MagicMock(id=uuid4())]
        db.get = _get
        db.execute = _exec(script_rows)
        db.commit = AsyncMock()

        with patch("app.services.test_set_service.run_scripts_task") as mock_task:
            mock_task.delay.return_value = MagicMock(id="task-1")
            svc = TestSetService(db)
            result = await svc.run_set(str(uuid4()), headless=True, fail_fast=False)
            assert "session_id" in result and "exec_id" in result
            mock_task.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_empty_set_raises(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1"]
        # 查不到脚本 → 空
        db.get = _get(ts)
        db.execute = _exec([])
        svc = TestSetService(db)
        with pytest.raises(ValueError, match="脚本"):
            await svc.run_set(str(uuid4()))
```

- [ ] **Step 2: 实现**

```python
    async def run_set(self, set_id: str, headless: bool = True,
                      fail_fast: bool = False, timeout: int = 60) -> Dict:
        """执行测试集：解析 case_ids → script_asset（is_finalized 无硬性要求，但优先 converted）
        → run_scripts_task（exec_type=ui_testset）→ 更新 status=running。"""
        from app.models.test_case import ScriptAsset
        from app.tasks.script_tasks import run_scripts_task
        import uuid as _uuid

        ts = await self.db.get(TestSet, _uuid.UUID(set_id))
        if not ts:
            raise ValueError("测试集不存在")
        if not ts.case_ids:
            raise ValueError("测试集为空，请先添加用例")
        # case_ids → scripts（每 case 最新一条）
        case_uuids = [_uuid.UUID(c) for c in ts.case_ids]
        result = await self.db.execute(
            select(ScriptAsset).where(ScriptAsset.case_id.in_(case_uuids))
            .order_by(ScriptAsset.created_at.desc()))
        scripts = result.scalars().all()
        # 每 case 取最新
        by_case = {}
        for s in scripts:
            by_case.setdefault(str(s.case_id), s)
        script_ids = [str(s.id) for s in by_case.values()]
        if not script_ids:
            raise ValueError("测试集中的用例尚无已转换脚本，请先在「用例转自动化脚本」转换")

        session_id = str(_uuid.uuid4())
        config = {"headless": headless, "timeout": timeout, "max_failures": 0 if fail_fast else 100}
        task = run_scripts_task.delay(session_id=session_id, script_ids=script_ids,
                                      config=config, exec_type="ui_testset")
        ts.status = "running"
        await self.db.commit()
        return {"session_id": session_id, "task_id": task.id,
                "sse_url": f"/api/sse/stream/{session_id}", "script_count": len(script_ids)}
```

**报告聚合端点**：`GET /test-sets/{id}/report` —— 按 last_exec_id 查 ExecutionRecord + ExecutionDetail（含 screenshot_url），失败截图 URL 直出。

**执行结果回写**（run_scripts_task 完成后回填 last_run_at/last_pass_rate/last_exec_id/status=done）——实现方式：在 script_tasks 的 run 完成回调处，或测试集执行包一层监控任务（实现者按现有 run_scripts_task 结构选最小侵入方案，报告决策）。

- [ ] **Step 3: 测试过 + Commit** `feat(testset): run orchestration + report aggregation`

---

### Task 5: 可自动化评级透出

**Files:**
- Modify: `backend/app/api/v1/test_cases.py`（确认 to_dict 含 feasibility_level——阶段前已查有该列）
- Test: `backend/tests/test_test_case_api.py`（追加断言）

- [ ] **Step 1: 验证 CaseDetailResponse/CaseListResponse 已含 feasibility_level 字段（grep schemas/test_case.py）**
- [ ] **Step 2: 缺则补（列表/详情都透出）；有则写一个锁定测试**
- [ ] **Step 3: Commit** `feat(cases): automation feasibility surfaced in list/detail`

---

### Task 6: 前端 — 转脚本页改造 + StepEditor 组件

**Files:**
- Create: `frontend/src/components/StepEditor.vue`
- Modify: `frontend/src/views/ScriptConvert.vue`
- Create: `frontend/src/api/testSet.js`
- Modify: `frontend/src/api/script.js`（saveScriptSteps）

- [ ] **Step 1: StepEditor.vue**（核心组件，独立可复用）
  - props: `title`, `steps`（行数组）；emit: `save(steps)`
  - 每行：序号 | 操作类型下拉（SUPPORTED_ACTIONS 8 种中文标签：打开页面/点击/输入/下拉选择/等待/断言文本/断言可见/数据库断言）| target（元素定位输入框，支持手填）| value/参数 | expected（仅 assert_db 显示）| 删除按钮
  - 「+ 添加步骤」追加空行；拖拽或上下箭头调序（交换 seq）
  - 底部「保存脚本」→ emit save
  - assert_db 行加「AI 生成 SQL」小按钮（调 aiCaseAPI 或复用 gateway chat——实现者查现有前端 AI 调用模式，无现成的就留 TODO 标记按钮 disabled + tooltip "二期"）

- [ ] **Step 2: ScriptConvert.vue 改造**
  - Tab1 转脚本：左侧页面树（数据源 GET /test-cases 按 case 分组或复用 AI 生成页的 groupedPoints 模式——实现者查 /ai-case-generation/test-cases 返回结构，按 point/page 分组）+ 勾选用例 → 右侧「本次测试集」卡
  - 「批量转脚本」→ 转换弹窗（内嵌 SSE 直播 log-box，复用现有 startSSE）
  - 转换完成 → 弹窗内每条脚本「查看/编辑脚本」按钮 → 打开 StepEditor（steps 从 script.step_mapping 还原）→ 保存调 saveScriptSteps
  - 「存为测试集」→ ElMessageBox.prompt 输入名称 → POST /test-sets（source=convert_page）

- [ ] **Step 3: build 验证 + Commit** `feat(ui): convert page tree + SSE modal + StepEditor + save-as-testset`

---

### Task 7: 前端 — UI自动化测试页

**Files:**
- Create: `frontend/src/views/AutoUITest.vue`
- Modify: `frontend/src/router/index.js`（/auto/ui 改为组件页，不再 redirect）

- [ ] **Step 1: AutoUITest.vue**（蓝本：原型 scripts section + ScriptConvert 现有脚本库 Tab）
  - **测试集 Tab**：列表（名称/来源/用例数/最近执行/通过率/状态）+ 详情区（用例表 + 「▶ 执行测试集」→ 执行配置弹窗（无头 checkbox 默认开 / fail_fast / 超时）→ 提交后 SSE 直播区（复用 log-box 模式）+ 完成后「查看报告」
  - 报告 drawer：执行摘要（badge 通过率/用例数/耗时）+ 逐用例 ✅❌ 行 + **失败用例内嵌截图**（execution_detail.screenshot_url 的 img）+ 失败原因（error_type 中文映射）
  - **脚本库 Tab**：复用/迁移 ScriptConvert 现有脚本库列表（名称/状态/上次结果/AI诊断/查看代码）+ 每行「编辑脚本」→ StepEditor
- [ ] **Step 2: 路由**：/auto/ui → AutoUITest.vue（ScriptConvertAlias 保留 /ai/convert）
- [ ] **Step 3: build + Commit** `feat(ui): AutoUITest page — testset exec + report with failure screenshots`

---

### Task 8: 阶段2 收官验收

- [ ] **Step 1: 全量测试**（≥700 passed 预期）
- [ ] **Step 2: 真浏览器验收清单**：
  1. /ai/convert：页面树勾选 → 转换弹窗 SSE 直播 → 完成后查看/编辑脚本（StepEditor 加一步 assert_db → 保存 → 重新查看代码含生成的脚本）
  2. 存为测试集 → /auto/ui 测试集 Tab 可见
  3. 执行测试集（无头）→ SSE 直播 → 报告含通过率/截图
  4. 旧入口 /auto/ui redirect 不再生效（直接是页面）
  5. Console 无报错
- [ ] **Step 3: 收官存档**

---

## Self-Review 结果

- **Spec 覆盖**：转脚本页改造（T6）/测试集模型+CRUD+执行（T0/T3/T4）/步骤化编辑器含 assert_db（T1/T2/T6）/UI自动化测试页+报告+失败截图（T7）/可自动化评级（T5）——定稿阶段2 范围全覆盖。删回归页属阶段3（菜单重组时一起，本阶段 /auto/regression 保留）。
- **类型一致性**：generate_script/SUPPORTED_ACTIONS（T1 定义，T2 消费）；TestSetService.create_set/add_cases/remove_case/run_set/report（T3 定义 T4 扩展）；save_steps（T2）。
- **风险已标注**：① assert_db 执行注入（Task 4 与 script_executor 的 runner 协作）是全计划最不确定点——T1 只生成、T4 注入，若 runner 不支持则 Task 4 报告并降级（assert_db 生成但执行时 skip+提示）；② run 结果回写 test_set 的侵入点需实现者探查 run_scripts_task 现有结构后决策；③ 脚本库 Tab 从 ScriptConvert 迁移还是复用引用，实现者定（倾向迁移，让 /ai/convert 专注转换）。
