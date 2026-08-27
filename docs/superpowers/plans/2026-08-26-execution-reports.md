# 执行记录与报告（#6）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** #6 报告中心——执行记录列表（项目隔离+筛选+分页）+ 报告详情页（统计+失败明细+截图+最简趋势）+ 导出 HTML/PDF，只读消费 #5a 的 execution_record/ExecutionDetail。

**Architecture:** 单 router `reports.py`（prefix /reports）+ 2 service（ExecutionQueryService 读取聚合 / ReportGenerator 渲染导出）+ notifier stub。Jinja2 模板渲染 HTML，weasyprint 转 PDF，产物存 MinIO（复用 storage_client），key 回写 execution_record.report_url。报告幂等（report_url 非空跳过，force 重生成）。

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Jinja2, weasyprint, openpyxl(已在), pytest, pytest-asyncio, Vue3, Element Plus, ECharts。

**Spec:** `docs/superpowers/specs/2026-08-25-execution-reports-design.md`

**测试约定：** 后端测试 `cd backend && PYTHONUTF8=1 python -m pytest`（Windows GBK 控制台须 PYTHONUTF8=1）。conftest.py 已 mock sys.path。无 DB 时用 mock AsyncSession；weasyprint/Jinja2/storage 全 mock。

**Git 约定：** worktree 分支 `worktree-module6-execution-reports`（基于最新 master，含 #5a+#10）。每 task 末尾 commit。message 前缀 `feat(reports):`/`fix(reports):`/`refactor(reports):`/`test(reports):`/`chore(reports):`。

**边界：** 只读消费 execution_record/execution_detail（import 不改字段）。不碰 script_executor.py、tasks/、api/v1/scripts.py（#5a 领地）。共享文件：api/__init__.py（追加 router）、requirements.txt（加 weasyprint/Jinja2）、router/index.js + MainLayout.vue（菜单路由，追加）。

---

## File Structure（新建/修改文件总览）

**后端新建：**
- `backend/app/services/execution_query_service.py` — 记录列表/详情/明细/趋势聚合
- `backend/app/services/report_generator.py` — Jinja2 HTML + weasyprint PDF + MinIO 上传 + 回写 report_url
- `backend/app/services/notifier.py` — P1 推送 stub（钉钉/微信扩展口）
- `backend/app/schemas/report.py` — 报告相关 schema
- `backend/app/api/v1/reports.py` — 单 router prefix /reports
- `backend/app/templates/report.html` — Jinja2 报告模板
- `backend/tests/test_execution_query_service.py`
- `backend/tests/test_report_generator.py`
- `backend/tests/test_api_reports.py`

**后端修改：**
- `backend/app/core/storage.py` — 加 `get_object_bytes(object_name)` 方法（导出端点读报告产物）
- `backend/app/api/__init__.py` — 注册 reports router
- `backend/requirements.txt` — 加 weasyprint + Jinja2

**前端新建：**
- `frontend/src/views/reports/ExecutionList.vue` — 执行记录列表 + 趋势块
- `frontend/src/views/reports/ReportDetail.vue` — 报告详情整合视图
- `frontend/src/api/report.js` — 封装 /reports/*

**前端修改：**
- `frontend/src/router/index.js` — 加 /reports + /reports/:execId
- `frontend/src/layouts/MainLayout.vue` — 菜单「执行记录与报告」改指 /reports

---

## Task 1: storage 加 get_object_bytes

**Files:**
- Modify: `backend/app/core/storage.py`
- Test: `backend/tests/test_storage_get_object.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_storage_get_object.py`:

```python
"""storage get_object_bytes tests."""
import pytest
from unittest.mock import MagicMock, patch
from app.core.storage import StorageClient


def test_get_object_bytes_returns_bytes():
    client = StorageClient()
    client.client = MagicMock()
    fake_response = MagicMock()
    fake_response.read.return_value = b"<html>report</html>"
    fake_response.stream = [b"<html>report</html>"]
    fake_response.__iter__ = lambda self: iter([b"<html>report</html>"])
    client.client.get_object.return_value = fake_response
    # patch the stream read approach
    client.client.get_object.return_value = MagicMock(
        stream=[b"<html>", b"report</html>"]
    )
    data = client.get_object_bytes("reports/exec-1.html")
    assert b"<html>report</html>" in data


def test_get_object_bytes_fallback_when_no_client():
    client = StorageClient()
    client.client = None
    client._fallback_store["reports/x.html"] = b"fallback-data"
    data = client.get_object_bytes("reports/x.html")
    assert data == b"fallback-data"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_storage_get_object.py -v`
Expected: FAIL（方法不存在）

- [ ] **Step 3: 实现 get_object_bytes**

在 `backend/app/core/storage.py` 的 `object_exists` 方法后加：

```python
    def get_object_bytes(self, object_name: str) -> bytes:
        """读取 MinIO 对象字节数据（用于报告导出/查看）。降级时从内存取。"""
        try:
            if self.client is None:
                return self._fallback_store.get(object_name, b"")
            response = self.client.get_object(self.bucket_name, object_name)
            data = b"".join(response.stream)
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"Failed to get object {object_name}: {e}")
            raise Exception(f"Storage get failed: {str(e)}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_storage_get_object.py -v`
Expected: PASS

- [ ] **Step 5: 跑全量无回归**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（321+2）

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/core/storage.py tests/test_storage_get_object.py
git commit -m "feat(reports): storage get_object_bytes for report export (W6)"
```

---

## Task 2: report schema

**Files:**
- Create: `backend/app/schemas/report.py`

- [ ] **Step 1: 写 schema**

Create `backend/app/schemas/report.py`:

```python
"""Report schemas."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class ExecutionRecordResponse(BaseModel):
    id: str
    exec_id: str
    project_id: str
    exec_type: str
    status: str
    total_cases: int = 0
    passed_count: int = 0
    fail_count: int = 0
    pass_rate: float = 0.0
    duration_ms: int = 0
    tokens_used: int = 0
    env_info: Optional[Dict[str, Any]] = None
    report_url: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class ExecutionRecordListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ExecutionRecordResponse]


class ExecutionDetailResponse(BaseModel):
    id: str
    execution_record_id: str
    script_id: Optional[str] = None
    case_id: Optional[str] = None
    step: Optional[int] = None
    action: Optional[str] = None
    status: str
    error_type: Optional[str] = None
    error_msg: Optional[str] = None
    stack_trace: Optional[str] = None
    screenshot_url: Optional[str] = None
    dom_snapshot: Optional[str] = None
    heal_status: Optional[str] = None
    heal_log: Optional[Any] = None
    duration_ms: int = 0
    created_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class ReportDetailResponse(BaseModel):
    """报告详情：ExecutionRecord + 聚合统计 + 失败明细"""
    record: ExecutionRecordResponse
    fail_step_count: int = 0
    total_duration_ms: int = 0
    token_remaining: Optional[int] = None  # 可选，联调时从 #10 token_service 取
    details: List[ExecutionDetailResponse] = []


class TrendItem(BaseModel):
    date: str
    pass_rate: float = 0.0
    exec_count: int = 0


class TrendResponse(BaseModel):
    project_id: str
    days: int
    items: List[TrendItem]


class GenerateReportResponse(BaseModel):
    html_url: Optional[str] = None
    pdf_url: Optional[str] = None
    regenerated: bool = False
```

- [ ] **Step 2: 验证导入**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.schemas.report import ExecutionRecordResponse, ReportDetailResponse, TrendResponse, GenerateReportResponse; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
cd backend
git add app/schemas/report.py
git commit -m "feat(reports): pydantic schemas for records/details/trend (W6)"
```

---

## Task 3: ExecutionQueryService

**Files:**
- Create: `backend/app/services/execution_query_service.py`
- Test: `backend/tests/test_execution_query_service.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_execution_query_service.py`:

```python
"""ExecutionQueryService tests."""
import pytest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.services.execution_query_service import ExecutionQueryService


def _mock_scalars(values):
    return Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=values))))


def _mock_scalar(value):
    return Mock(scalar=Mock(return_value=value))


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


class TestListRecords:
    @pytest.mark.asyncio
    async def test_list_returns_paginated(self, mock_db):
        r = Mock(); r.to_dict = Mock(return_value={"id": "1", "exec_id": "EXEC-1"})
        mock_db.execute.side_effect = [
            _mock_scalar(5),  # total count
            _mock_scalars([r]),  # rows
        ]
        svc = ExecutionQueryService(mock_db)
        result = await svc.list_records(str(uuid4()), page=1, page_size=20)
        assert result["total"] == 5
        assert len(result["items"]) == 1
        assert result["items"][0]["exec_id"] == "EXEC-1"

    @pytest.mark.asyncio
    async def test_list_filters_by_type(self, mock_db):
        mock_db.execute.side_effect = [_mock_scalar(0), _mock_scalars([])]
        svc = ExecutionQueryService(mock_db)
        result = await svc.list_records(str(uuid4()), exec_type="ui_regression")
        assert result["total"] == 0


class TestGetDetail:
    @pytest.mark.asyncio
    async def test_get_detail_returns_record_and_fail_count(self, mock_db):
        rec = Mock()
        rec.to_dict = Mock(return_value={"id": "1", "exec_id": "EXEC-1", "total_cases": 10})
        fail_detail = Mock(); fail_detail.to_dict = Mock(return_value={"id": "d1", "status": "fail"})
        # 1st: record, 2nd: fail count scalar, 3rd: details list
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=rec)),
            _mock_scalar(2),
            _mock_scalars([fail_detail]),
        ]
        svc = ExecutionQueryService(mock_db)
        result = await svc.get_detail("exec-1")
        assert result["record"]["exec_id"] == "EXEC-1"
        assert result["fail_step_count"] == 2
        assert len(result["details"]) == 1

    @pytest.mark.asyncio
    async def test_get_detail_missing_returns_none(self, mock_db):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = ExecutionQueryService(mock_db)
        assert await svc.get_detail("no-such") is None


class TestTrend:
    @pytest.mark.asyncio
    async def test_trend_aggregates_by_day(self, mock_db):
        # date_trunc rows: (day, avg_pass_rate, count)
        rows = [("2026-08-25", 92.5, 3), ("2026-08-24", 85.0, 5)]
        mock_db.execute.return_value = Mock(all=Mock(return_value=rows))
        svc = ExecutionQueryService(mock_db)
        result = await svc.get_trend(str(uuid4()), days=7)
        assert len(result) == 2
        assert result[0]["date"] == "2026-08-25"
        assert result[0]["pass_rate"] == 92.5
        assert result[0]["exec_count"] == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_execution_query_service.py -v`
Expected: FAIL（service 不存在）

- [ ] **Step 3: 实现 service**

Create `backend/app/services/execution_query_service.py`:

```python
"""Execution query service: read-only aggregation over execution_record/execution_detail."""
import logging
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionRecord, ExecutionDetail

logger = logging.getLogger(__name__)


class ExecutionQueryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_records(self, project_id: str, *, exec_type: Optional[str] = None,
                          days: int = 7, page: int = 1, page_size: int = 20) -> dict:
        pid = UUID(project_id)
        since = datetime.now(timezone.utc) - timedelta(days=days)
        base = select(ExecutionRecord).where(
            ExecutionRecord.project_id == pid,
            ExecutionRecord.started_at >= since,
        )
        if exec_type:
            base = base.where(ExecutionRecord.exec_type == exec_type)

        total_q = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(total_q)).scalar() or 0

        rows_q = base.order_by(ExecutionRecord.started_at.desc()).offset(
            (page - 1) * page_size).limit(page_size)
        rows = (await self.db.execute(rows_q)).scalars().all()
        return {"total": total, "page": page, "page_size": page_size,
                "items": [r.to_dict() for r in rows]}

    async def get_detail(self, exec_id: str) -> Optional[dict]:
        rec_q = select(ExecutionRecord).where(ExecutionRecord.exec_id == exec_id)
        rec = (await self.db.execute(rec_q)).scalar_one_or_none()
        if not rec:
            return None

        fail_count_q = select(func.count()).select_from(ExecutionDetail).where(
            ExecutionDetail.execution_record_id == rec.id,
            ExecutionDetail.status == "fail",
        )
        fail_step_count = (await self.db.execute(fail_count_q)).scalar() or 0

        details_q = (select(ExecutionDetail)
                     .where(ExecutionDetail.execution_record_id == rec.id,
                            ExecutionDetail.status == "fail")
                     .order_by(ExecutionDetail.step))
        details = (await self.db.execute(details_q)).scalars().all()

        return {
            "record": rec.to_dict(),
            "fail_step_count": fail_step_count,
            "total_duration_ms": rec.duration_ms or 0,
            "token_remaining": None,
            "details": [d.to_dict() for d in details],
        }

    async def list_details(self, exec_id: str, *, status: Optional[str] = "fail") -> list:
        rec_q = select(ExecutionRecord).where(ExecutionRecord.exec_id == exec_id)
        rec = (await self.db.execute(rec_q)).scalar_one_or_none()
        if not rec:
            return []
        q = select(ExecutionDetail).where(ExecutionDetail.execution_record_id == rec.id)
        if status:
            q = q.where(ExecutionDetail.status == status)
        q = q.order_by(ExecutionDetail.step)
        rows = (await self.db.execute(q)).scalars().all()
        return [r.to_dict() for r in rows]

    async def get_trend(self, project_id: str, days: int = 7) -> list:
        pid = UUID(project_id)
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (
            select(
                func.date_trunc("day", ExecutionRecord.started_at).label("d"),
                func.avg(ExecutionRecord.pass_rate).label("avg_rate"),
                func.count().label("cnt"),
            )
            .where(ExecutionRecord.project_id == pid, ExecutionRecord.started_at >= since)
            .group_by("d").order_by("d")
        )
        rows = (await self.db.execute(q)).all()
        return [
            {"date": str(r[0].date()) if r[0] else "",
             "pass_rate": float(r[1]) if r[1] is not None else 0.0,
             "exec_count": r[2]}
            for r in rows
        ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_execution_query_service.py -v`
Expected: PASS（5 tests）

- [ ] **Step 5: 跑全量无回归**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/execution_query_service.py tests/test_execution_query_service.py
git commit -m "feat(reports): ExecutionQueryService list/detail/trend aggregation (W6)"
```

---

## Task 4: notifier stub

**Files:**
- Create: `backend/app/services/notifier.py`
- Test: `backend/tests/test_notifier.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_notifier.py`:

```python
"""Notifier stub tests (P1 push placeholder)."""
import pytest
from app.services.notifier import Notifier, notify_report_ready


@pytest.mark.asyncio
async def test_notify_does_not_raise():
    n = Notifier()
    # should not raise (stub)
    await n.notify_report_ready("exec-1", {"html_url": "x"})


@pytest.mark.asyncio
async def test_module_helper():
    # should not raise
    await notify_report_ready("exec-1", {"score": 90})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_notifier.py -v`
Expected: FAIL（不存在）

- [ ] **Step 3: 实现 notifier**

Create `backend/app/services/notifier.py`:

```python
"""Notifier — P1 push placeholder. Stub now; later wire 钉钉/微信 webhook."""
import logging

logger = logging.getLogger(__name__)


class Notifier:
    async def notify_report_ready(self, exec_id: str, meta: dict):
        """P1 预留：本期仅日志；后期对接钉钉/微信 webhook。
        webhook 配置复用 #10 SystemSettingService（notify category）。"""
        logger.info(f"[notifier stub] report ready for {exec_id}: {meta}")


async def notify_report_ready(exec_id: str, meta: dict):
    """Module-level convenience helper."""
    await Notifier().notify_report_ready(exec_id, meta)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_notifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/services/notifier.py tests/test_notifier.py
git commit -m "feat(reports): notifier stub for P1 push (钉钉/微信 later) (W6)"
```

---

## Task 5: report.html Jinja2 模板

**Files:**
- Create: `backend/app/templates/report.html`

- [ ] **Step 1: 写模板**

Create `backend/app/templates/report.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: "Microsoft YaHei", sans-serif; margin: 30px; color: #303133; }
  h1 { color: #409eff; border-bottom: 2px solid #409eff; padding-bottom: 8px; }
  .meta { color: #909399; font-size: 13px; margin-bottom: 20px; }
  .cards { display: flex; gap: 16px; margin: 20px 0; }
  .card { border: 1px solid #ebeef5; border-radius: 4px; padding: 16px; flex: 1; text-align: center; }
  .card .num { font-size: 24px; font-weight: 600; }
  .card .lbl { color: #909399; font-size: 12px; margin-top: 4px; }
  .pass { color: #67c23a; } .fail { color: #f56c6c; } .rate { color: #409eff; }
  table { width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }
  th, td { border: 1px solid #ebeef5; padding: 8px; text-align: left; }
  th { background: #f5f7fa; }
  .err { color: #f56c6c; font-family: monospace; font-size: 12px; }
  .stack { background: #fafafa; padding: 8px; font-family: monospace; font-size: 11px; white-space: pre-wrap; }
  img.screenshot { max-width: 300px; border: 1px solid #ebeef5; }
  footer { margin-top: 30px; color: #c0c4cc; font-size: 11px; border-top: 1px solid #ebeef5; padding-top: 8px; }
</style>
</head>
<body>
<h1>MoonTest 执行报告</h1>
<div class="meta">
  执行ID：{{ record.exec_id }} | 类型：{{ record.exec_type }} | 环境：{{ env_info }} |
  耗时：{{ duration_sec }}秒 | 时间：{{ record.started_at }}
</div>

<div class="cards">
  <div class="card"><div class="num">{{ record.total_cases }}</div><div class="lbl">总用例</div></div>
  <div class="card"><div class="num pass">{{ record.passed_count }}</div><div class="lbl">通过</div></div>
  <div class="card"><div class="num fail">{{ record.fail_count }}</div><div class="lbl">失败</div></div>
  <div class="card"><div class="num rate">{{ record.pass_rate }}%</div><div class="lbl">通过率</div></div>
  <div class="card"><div class="num">{{ record.tokens_used }}</div><div class="lbl">Token消耗</div></div>
</div>

<h2>失败步骤明细</h2>
{% if details %}
<table>
  <tr><th>步骤</th><th>动作</th><th>错误类型</th><th>错误信息</th><th>截图</th></tr>
  {% for d in details %}
  <tr>
    <td>{{ d.step }}</td>
    <td>{{ d.action }}</td>
    <td class="err">{{ d.error_type or '-' }}</td>
    <td class="err">{{ d.error_msg or '-' }}</td>
    <td>{% if d.screenshot_url %}<img class="screenshot" src="{{ d.screenshot_url }}">{% else %}-{% endif %}</td>
  </tr>
  {% if d.stack_trace %}<tr><td colspan="5"><div class="stack">{{ d.stack_trace }}</div></td></tr>{% endif %}
  {% endfor %}
</table>
{% else %}
<p>无失败步骤</p>
{% endif %}

<footer>由 MoonTest 自动生成 | {{ generated_at }}</footer>
</body>
</html>
```

- [ ] **Step 2: 确认文件存在**

Run: `cd backend && ls app/templates/report.html`
Expected: lists file

- [ ] **Step 3: Commit**

```bash
cd backend
git add app/templates/report.html
git commit -m "feat(reports): Jinja2 report template (W6)"
```

---

## Task 6: ReportGenerator

**Files:**
- Create: `backend/app/services/report_generator.py`
- Test: `backend/tests/test_report_generator.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_report_generator.py`:

```python
"""ReportGenerator tests (weasyprint/Jinja2/storage all mocked)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.report_generator import ReportGenerator


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def record_with_detail(mock_db):
    rec = MagicMock()
    rec.id = uuid4()
    rec.exec_id = "EXEC-20260826-1"
    rec.project_id = uuid4()
    rec.exec_type = "ui_regression"
    rec.status = "success"
    rec.total_cases = 10
    rec.passed_count = 8
    rec.fail_count = 2
    rec.pass_rate = 80.0
    rec.duration_ms = 154000
    rec.tokens_used = 3457
    rec.env_info = {"browser": "chromium"}
    rec.report_url = None
    rec.started_at = None
    rec.finished_at = None
    rec.to_dict = MagicMock(return_value={
        "exec_id": "EXEC-20260826-1", "exec_type": "ui_regression", "total_cases": 10,
        "passed_count": 8, "fail_count": 2, "pass_rate": 80.0, "tokens_used": 3457,
        "started_at": None, "env_info": {"browser": "chromium"},
    })
    detail = MagicMock()
    detail.to_dict = MagicMock(return_value={
        "step": 2, "action": "click", "error_type": "locate_failed",
        "error_msg": "not found", "screenshot_url": "http://minio/x.png",
        "stack_trace": "Traceback...",
    })
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=rec)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[detail])))),
    ]
    return rec


class TestGenerateReport:
    @pytest.mark.asyncio
    async def test_generate_renders_and_uploads(self, mock_db, record_with_detail):
        gen = ReportGenerator(mock_db)
        with patch("app.services.report_generator.render_template", return_value="<html>report</html>") as mock_render, \
             patch("app.services.report_generator.storage_client") as mock_storage, \
             patch("app.services.report_generator.notify_report_ready", new=AsyncMock()):
            mock_storage.upload_bytes = AsyncMock(side_effect=[
                "reports/exec.html", "reports/exec.pdf"
            ])
            with patch("app.services.report_generator.HTML") as mock_html_cls:
                mock_html = MagicMock()
                mock_html.write_pdf.return_value = b"%PDF-fake"
                mock_html_cls.return_value = mock_html
                result = await gen.generate_report("EXEC-20260826-1")
        assert result["html_url"] == "reports/exec.html"
        assert result["pdf_url"] == "reports/exec.pdf"
        assert result["regenerated"] is True
        assert record_with_detail.report_url == "reports/exec.html"
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_generate_skips_when_already_generated(self, mock_db, record_with_detail):
        record_with_detail.report_url = "reports/exec.html"  # already has
        gen = ReportGenerator(mock_db)
        result = await gen.generate_report("EXEC-20260826-1")
        assert result["regenerated"] is False
        assert result["html_url"] == "reports/exec.html"

    @pytest.mark.asyncio
    async def test_force_regenerates(self, mock_db, record_with_detail):
        record_with_detail.report_url = "reports/old.html"
        gen = ReportGenerator(mock_db)
        with patch("app.services.report_generator.render_template", return_value="<html>new</html>"), \
             patch("app.services.report_generator.storage_client") as mock_storage, \
             patch("app.services.report_generator.notify_report_ready", new=AsyncMock()), \
             patch("app.services.report_generator.HTML") as mock_html_cls:
            mock_storage.upload_bytes = AsyncMock(side_effect=["reports/exec.html", "reports/exec.pdf"])
            mock_html_cls.return_value.write_pdf.return_value = b"%PDF"
            result = await gen.generate_report("EXEC-20260826-1", force=True)
        assert result["regenerated"] is True

    @pytest.mark.asyncio
    async def test_generate_missing_record_returns_none(self, mock_db):
        mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        gen = ReportGenerator(mock_db)
        assert await gen.generate_report("no-such") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_report_generator.py -v`
Expected: FAIL（service 不存在）

- [ ] **Step 3: 实现 ReportGenerator**

Create `backend/app/services/report_generator.py`:

```python
"""Report generator: Jinja2 HTML + weasyprint PDF + MinIO upload + report_url writeback."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionRecord, ExecutionDetail
from app.core.storage import storage_client
from app.services.notifier import notify_report_ready

logger = logging.getLogger(__name__)


def render_template(template_name: str, **context) -> str:
    """Render a Jinja2 template. Imported lazily so tests can mock it."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    import os
    tmpl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(tmpl_dir), autoescape=select_autoescape(["html"]))
    tmpl = env.get_template(template_name)
    return tmpl.render(**context)


class ReportGenerator:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_report(self, exec_id: str, *, force: bool = False) -> dict:
        rec_q = select(ExecutionRecord).where(ExecutionRecord.exec_id == exec_id)
        rec = (await self.db.execute(rec_q)).scalar_one_or_none()
        if not rec:
            return None

        # idempotent: skip if already generated unless force
        if rec.report_url and not force:
            return {"html_url": rec.report_url, "pdf_url": self._pdf_key(exec_id), "regenerated": False}

        # fetch fail details
        det_q = (select(ExecutionDetail)
                 .where(ExecutionDetail.execution_record_id == rec.id,
                        ExecutionDetail.status == "fail")
                 .order_by(ExecutionDetail.step))
        details = (await self.db.execute(det_q)).scalars().all()

        env_info = rec.env_info if isinstance(rec.env_info, dict) else {}
        env_str = env_info.get("browser", "-")
        duration_sec = round((rec.duration_ms or 0) / 1000, 1)

        # render HTML
        html = render_template(
            "report.html",
            record=rec.to_dict(),
            details=[d.to_dict() for d in details],
            env_info=env_str,
            duration_sec=duration_sec,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        # render PDF
        try:
            from weasyprint import HTML
            pdf_bytes = HTML(string=html).write_pdf()
        except Exception as e:
            logger.warning(f"weasyprint failed (non-fatal, PDF skipped): {e}")
            pdf_bytes = None

        # upload to MinIO
        html_key = f"reports/{exec_id}.html"
        await storage_client.upload_bytes(html.encode("utf-8"), html_key)
        pdf_key = None
        if pdf_bytes:
            pdf_key = f"reports/{exec_id}.pdf"
            await storage_client.upload_bytes(pdf_bytes, pdf_key)

        # write back report_url
        rec.report_url = html_key
        await self.db.commit()

        # notify (P1 stub)
        await notify_report_ready(exec_id, {"html_url": html_key, "pdf_url": pdf_key})

        return {"html_url": html_key, "pdf_url": pdf_key, "regenerated": True}

    def _pdf_key(self, exec_id: str) -> str:
        return f"reports/{exec_id}.pdf"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_report_generator.py -v`
Expected: PASS（4 tests）

- [ ] **Step 5: 跑全量无回归**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/report_generator.py tests/test_report_generator.py
git commit -m "feat(reports): ReportGenerator HTML+PDF+MinIO+idempotent (W6)"
```

---

## Task 7: reports API router

**Files:**
- Create: `backend/app/api/v1/reports.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_api_reports.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_api_reports.py`:

```python
"""Reports API endpoint tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _override(mock_svc):
    from app.api.v1.reports import get_query_service, get_generator_service
    app.dependency_overrides[get_query_service] = lambda: mock_svc
    app.dependency_overrides[get_generator_service] = lambda: mock_svc


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


class TestRecords:
    def test_list_records(self, client):
        svc = MagicMock()
        svc.list_records = AsyncMock(return_value={"total": 1, "page": 1, "page_size": 20,
                                                   "items": [{"id": "1", "exec_id": "E1"}]})
        _override(svc)
        r = client.get("/api/v1/reports/records?project_id=00000000-0000-0000-0000-000000000001")
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 1

    def test_get_detail(self, client):
        svc = MagicMock()
        svc.get_detail = AsyncMock(return_value={"record": {"exec_id": "E1"}, "fail_step_count": 2,
                                                 "details": []})
        _override(svc)
        r = client.get("/api/v1/reports/records/E1")
        assert r.status_code == 200
        assert r.json()["data"]["fail_step_count"] == 2

    def test_get_detail_missing(self, client):
        svc = MagicMock()
        svc.get_detail = AsyncMock(return_value=None)
        _override(svc)
        r = client.get("/api/v1/reports/records/no-such")
        assert r.status_code == 404


class TestTrend:
    def test_trend(self, client):
        svc = MagicMock()
        svc.get_trend = AsyncMock(return_value=[{"date": "2026-08-26", "pass_rate": 90.0, "exec_count": 3}])
        _override(svc)
        r = client.get("/api/v1/reports/trend?project_id=00000000-0000-0000-0000-000000000001&days=7")
        assert r.status_code == 200
        assert r.json()["data"][0]["pass_rate"] == 90.0


class TestGenerate:
    def test_generate(self, client):
        gen = MagicMock()
        gen.generate_report = AsyncMock(return_value={"html_url": "reports/E1.html", "pdf_url": "reports/E1.pdf", "regenerated": True})
        _override(gen)
        r = client.post("/api/v1/reports/E1/generate")
        assert r.status_code == 200
        assert r.json()["data"]["regenerated"] is True


class TestExport:
    def test_export_html(self, client):
        from app.api.v1 import reports as reports_api
        reports_api.storage_client.get_object_bytes = MagicMock(return_value=b"<html>x</html>")
        # need a record so query service returns one with report_url
        svc = MagicMock()
        svc.get_detail = AsyncMock(return_value={"record": {"report_url": "reports/E1.html"}, "details": []})
        _override(svc)
        r = client.get("/api/v1/reports/E1/export?format=html")
        assert r.status_code == 200
        assert b"<html>" in r.content
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_reports.py -v`
Expected: FAIL（router 未注册）

- [ ] **Step 3: 实现 reports.py**

Create `backend/app/api/v1/reports.py`:

```python
"""Reports API endpoints (prefix /reports). Read-only over #5a execution tables."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.storage import storage_client
from app.services.execution_query_service import ExecutionQueryService
from app.services.report_generator import ReportGenerator

router = APIRouter()


def get_query_service(db: AsyncSession = Depends(get_db)) -> ExecutionQueryService:
    return ExecutionQueryService(db)

def get_generator_service(db: AsyncSession = Depends(get_db)) -> ReportGenerator:
    return ReportGenerator(db)


@router.get("/records")
async def list_records(
    project_id: str = Query(...),
    exec_type: str = Query(None),
    days: int = Query(7, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    svc: ExecutionQueryService = Depends(get_query_service),
):
    result = await svc.list_records(project_id, exec_type=exec_type, days=days, page=page, page_size=page_size)
    return {"code": 0, "data": result}


@router.get("/records/{exec_id}")
async def get_record_detail(exec_id: str, svc: ExecutionQueryService = Depends(get_query_service)):
    result = await svc.get_detail(exec_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return {"code": 0, "data": result}


@router.get("/records/{exec_id}/details")
async def list_details(exec_id: str, status: str = Query("fail"),
                       svc: ExecutionQueryService = Depends(get_query_service)):
    items = await svc.list_details(exec_id, status=status)
    return {"code": 0, "data": items}


@router.get("/trend")
async def get_trend(project_id: str = Query(...), days: int = Query(7, ge=1, le=90),
                    svc: ExecutionQueryService = Depends(get_query_service)):
    items = await svc.get_trend(project_id, days=days)
    return {"code": 0, "data": items}


@router.post("/{exec_id}/generate")
async def generate_report(exec_id: str, force: bool = Query(False),
                          gen: ReportGenerator = Depends(get_generator_service)):
    result = await gen.generate_report(exec_id, force=force)
    if result is None:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return {"code": 0, "data": result}


@router.get("/{exec_id}/export")
async def export_report(exec_id: str, format: str = Query("html", pattern="^(html|pdf)$"),
                        svc: ExecutionQueryService = Depends(get_query_service)):
    detail = await svc.get_detail(exec_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Execution record not found")
    key = f"reports/{exec_id}.{format}"
    try:
        data = storage_client.get_object_bytes(key)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Report {format} not generated yet")
    mime = "text/html" if format == "html" else "application/pdf"
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": f"attachment; filename=report-{exec_id}.{format}"})
```

- [ ] **Step 4: 注册 router**

Modify `backend/app/api/__init__.py`，import 行加 `reports`，include 行加：
```python
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_reports.py -v`
Expected: PASS（6 tests）

- [ ] **Step 6: 跑全量 + 路由核对**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; rs=[r.path for r in app.routes if '/reports' in getattr(r,'path','')]; [print(r) for r in sorted(set(rs))]"`
Expected: 6 /reports/* 路径

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/api/v1/reports.py app/api/__init__.py tests/test_api_reports.py
git commit -m "feat(reports): reports API router (records/details/trend/generate/export) (W6)"
```

---

## Task 8: 依赖更新

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 加依赖**

在 `backend/requirements.txt` 末尾加：
```
weasyprint
Jinja2
```
（不 pin 版本，让 pip 选兼容版；weasyprint 在 Windows 联调时可能装麻烦，开发期测试全 mock 不影响）

- [ ] **Step 2: Commit**

```bash
cd backend
git add requirements.txt
git commit -m "chore(reports): add weasyprint + Jinja2 deps (mocked in tests) (W6)"
```

---

## Task 9: 前端 API 封装

**Files:**
- Create: `frontend/src/api/report.js`

- [ ] **Step 1: 写 api/report.js**

Create `frontend/src/api/report.js`:

```javascript
import axios from './axios'

export const reportAPI = {
  listRecords(params) {
    return axios.get('/reports/records', { params }).then(r => r.data)
  },
  getDetail(execId) {
    return axios.get(`/reports/records/${execId}`).then(r => r.data)
  },
  listDetails(execId, status = 'fail') {
    return axios.get(`/reports/records/${execId}/details`, { params: { status } }).then(r => r.data)
  },
  getTrend(projectId, days = 7) {
    return axios.get('/reports/trend', { params: { project_id: projectId, days } }).then(r => r.data)
  },
  generateReport(execId, force = false) {
    return axios.post(`/reports/${execId}/generate`, null, { params: { force } }).then(r => r.data)
  },
  exportUrl(execId, format = 'html') {
    return `/reports/${execId}/export?format=${format}`
  }
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend
git add src/api/report.js
git commit -m "feat(reports): frontend API wrapper (W6)"
```

---

## Task 10: 前端 ExecutionList + ReportDetail 页

**Files:**
- Create: `frontend/src/views/reports/ExecutionList.vue`
- Create: `frontend/src/views/reports/ReportDetail.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/layouts/MainLayout.vue`

- [ ] **Step 1: 写 ExecutionList.vue**

Create `frontend/src/views/reports/ExecutionList.vue`:

```vue
<template>
  <div class="exec-list">
    <el-card>
      <template #header><span>执行记录与报告</span></template>
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="projectId" filterable @change="load" style="width: 240px">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="execType" clearable style="width: 160px" @change="load">
            <el-option label="UI回归" value="ui_regression" />
            <el-option label="接口" value="api" />
            <el-option label="白盒" value="whitebox" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间">
          <el-select v-model="days" style="width: 120px" @change="load">
            <el-option label="近7天" :value="7" />
            <el-option label="近30天" :value="30" />
            <el-option label="近90天" :value="90" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-card shadow="never" style="margin-bottom: 16px" v-loading="trendLoading">
        <template #header><span>通过率趋势（近{{ days }}天）</span></template>
        <div ref="trendChart" style="height: 200px" />
      </el-card>

      <el-table :data="records" v-loading="loading" border>
        <el-table-column prop="exec_id" label="执行ID" width="200" />
        <el-table-column prop="exec_type" label="类型" width="100" />
        <el-table-column prop="pass_rate" label="通过率" width="100">
          <template #default="{ row }">{{ row.pass_rate }}%</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'success' ? 'success' : 'danger'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="started_at" label="执行时间" width="180" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="primary" link @click="goDetail(row)">查看报告</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total"
        layout="total, prev, pager, next" @current-change="load" style="margin-top: 16px" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { reportAPI } from '@/api/report.js'
import { projectAPI } from '@/api/project.js'

const router = useRouter()
const projects = ref([])
const projectId = ref('')
const execType = ref('')
const days = ref(7)
const records = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const trendLoading = ref(false)
const trendChart = ref(null)
let chart = null

const loadProjects = async () => {
  const res = await projectAPI.list()
  projects.value = res.items || res || []
  if (projects.value.length) { projectId.value = projects.value[0].id; load() }
}
const load = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const res = await reportAPI.listRecords({ project_id: projectId.value, exec_type: execType.value, days: days.value, page: page.value, page_size: pageSize.value })
    const d = res.data || res
    records.value = d.items || []
    total.value = d.total || 0
    loadTrend()
  } catch (e) { console.error(e) } finally { loading.value = false }
}
const loadTrend = async () => {
  trendLoading.value = true
  try {
    const res = await reportAPI.getTrend(projectId.value, days.value)
    const items = (res.data || res) || []
    await nextTick()
    if (trendChart.value) {
      chart = echarts.init(trendChart.value)
      chart.setOption({
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: items.map(i => i.date) },
        yAxis: { type: 'value', max: 100 },
        series: [{ type: 'line', smooth: true, data: items.map(i => i.pass_rate), areaStyle: {} }]
      })
    }
  } finally { trendLoading.value = false }
}
const goDetail = (row) => router.push(`/reports/${row.exec_id}`)
onMounted(loadProjects)
</script>
<style scoped>.exec-list { padding: 20px; }</style>
```

- [ ] **Step 2: 写 ReportDetail.vue**

Create `frontend/src/views/reports/ReportDetail.vue`:

```vue
<template>
  <div class="report-detail" v-loading="loading">
    <el-card v-if="detail">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>报告详情：{{ detail.record.exec_id }}</span>
          <div>
            <el-button type="primary" size="small" :loading="generating" @click="generate(false)">生成报告</el-button>
            <el-button size="small" @click="generate(true)">重新生成</el-button>
            <el-button size="small" @click="exportReport('html')">导出HTML</el-button>
            <el-button size="small" @click="exportReport('pdf')">导出PDF</el-button>
          </div>
        </div>
      </template>
      <el-row :gutter="16">
        <el-col :span="5"><div class="stat"><div class="num">{{ detail.record.total_cases }}</div><div class="lbl">总用例</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num pass">{{ detail.record.passed_count }}</div><div class="lbl">通过</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num fail">{{ detail.record.fail_count }}</div><div class="lbl">失败</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num rate">{{ detail.record.pass_rate }}%</div><div class="lbl">通过率</div></div></el-col>
        <el-col :span="4"><div class="stat"><div class="num">{{ detail.record.tokens_used }}</div><div class="lbl">Token</div></div></el-col>
      </el-row>
      <el-descriptions :column="2" border style="margin-top: 16px">
        <el-descriptions-item label="类型">{{ detail.record.exec_type }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.record.status }}</el-descriptions-item>
        <el-descriptions-item label="耗时">{{ detail.record.duration_ms }}ms</el-descriptions-item>
        <el-descriptions-item label="失败步骤数">{{ detail.fail_step_count }}</el-descriptions-item>
        <el-descriptions-item label="执行时间">{{ detail.record.started_at }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">{{ detail.record.finished_at }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card style="margin-top: 16px" v-if="detail && detail.details.length">
      <template #header><span>失败步骤明细</span></template>
      <el-table :data="detail.details" border>
        <el-table-column prop="step" label="步骤" width="80" />
        <el-table-column prop="action" label="动作" width="120" />
        <el-table-column prop="error_type" label="错误类型" width="150">
          <template #default="{ row }"><el-tag type="danger" size="small">{{ row.error_type }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="error_msg" label="错误信息" min-width="200" show-overflow-tooltip />
        <el-table-column label="截图" width="120">
          <template #default="{ row }">
            <el-image v-if="row.screenshot_url" :src="row.screenshot_url" :preview-src-list="[row.screenshot_url]" style="width: 80px" />
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="堆栈" width="100">
          <template #default="{ row }">
            <el-popover v-if="row.stack_trace" trigger="click" width="600">
              <pre style="max-height: 300px; overflow: auto">{{ row.stack_trace }}</pre>
              <template #reference><el-button link>查看</el-button></template>
            </el-popover>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { reportAPI } from '@/api/report.js'
import axios from '@/api/axios.js'

const route = useRoute()
const loading = ref(false)
const generating = ref(false)
const detail = ref(null)

const load = async () => {
  loading.value = true
  try {
    const res = await reportAPI.getDetail(route.params.execId)
    detail.value = res.data || res
  } catch (e) { ElMessage.error('加载失败') } finally { loading.value = false }
}
const generate = async (force) => {
  generating.value = true
  try {
    await reportAPI.generateReport(route.params.execId, force)
    ElMessage.success(force ? '已重新生成' : '已生成')
    load()
  } catch (e) { ElMessage.error('生成失败') } finally { generating.value = false }
}
const exportReport = (format) => {
  window.location = axios.defaults.baseURL + reportAPI.exportUrl(route.params.execId, format)
}
onMounted(load)
</script>
<style scoped>
.report-detail { padding: 20px; }
.stat { text-align: center; border: 1px solid #ebeef5; border-radius: 4px; padding: 12px; }
.stat .num { font-size: 22px; font-weight: 600; } .stat .pass { color: #67c23a; }
.stat .fail { color: #f56c6c; } .stat .rate { color: #409eff; }
.stat .lbl { color: #909399; font-size: 12px; margin-top: 4px; }
</style>
```

- [ ] **Step 3: 路由 + 菜单**

Modify `frontend/src/router/index.js`，在 children 末尾（settings/tokens 后）加：
```javascript
        {
          path: 'reports',
          name: 'ExecutionList',
          component: () => import('@/views/reports/ExecutionList.vue'),
          meta: { title: '执行记录与报告' }
        },
        {
          path: 'reports/:execId',
          name: 'ReportDetail',
          component: () => import('@/views/reports/ReportDetail.vue'),
          meta: { title: '报告详情' }
        },
```

Modify `frontend/src/layouts/MainLayout.vue`：「质量与报告」子菜单「执行记录与报告」（现 index `/quality/report`）改为 `/reports`。

- [ ] **Step 4: 前端构建验证**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 5: Commit**

```bash
cd frontend
git add src/views/reports/ExecutionList.vue src/views/reports/ReportDetail.vue src/api/report.js src/router/index.js src/layouts/MainLayout.vue
git commit -m "feat(reports): ExecutionList + ReportDetail pages + routes (W6)"
```

---

## Task 11: 全量验证 + 收尾

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（321 + #6 新增 ~17 = 338+）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 路由核对**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; rs=[r.path for r in app.routes if '/reports' in getattr(r,'path','')]; [print(r) for r in sorted(set(rs))]"`
Expected: 6 个 /reports/* 路径

- [ ] **Step 4: 迁移脚本检查**

Run: `ls backend/migrations/*.sql | cat`
Expected: 含已有全部（#6 不新建迁移，只读 #5a 两表）

- [ ] **Step 5: 更新 TODO_LIST**

Modify `.claude/TODO_LIST.md`：标记 #6 完成，更新模块计数。

- [ ] **Step 6: 最终 Commit**

```bash
git add .claude/TODO_LIST.md
git commit -m "chore: update TODO_LIST (#6 execution reports done) (W6)"
```

---

## Self-Review 记录

**1. Spec 覆盖：**
- 不建表只读 #5a 两表 ✓ Task3 (query service) / Task6 (generator 读 detail)
- /reports 前缀独立（#5a 在 /scripts/*）✓ Task7
- 趋势仅通过率单一指标 ✓ Task3 get_trend
- 报告幂等 report_url IS NOT NULL + force ✓ Task6 (3 tests)
- notifier stub P1 ✓ Task4
- 导出 HTML/PDF ✓ Task6 + Task7 export
- 前端列表+详情+趋势 ✓ Task10
全部覆盖。

**2. 占位符扫描：** 无 TBD/TODO。Task6 测试 mock weasyprint/storage/render_template，符合"全 mock 联调真跑"策略。

**3. 类型一致性：** ExecutionQueryService.list_records/get_detail/list_details/get_trend 签名 service/task/api/前端全链路一致；ReportGenerator.generate_report(exec_id, force) 在 service/api/前端一致；storage.get_object_bytes 在 storage/export 端点一致。

**4. 边界核对：** 只读 execution.py（import 不改字段）；不碰 script_executor.py/tasks/scripts.py。共享文件：api/__init__.py（追加 router）+ requirements.txt（加 weasyprint/Jinja2）+ router/index.js + MainLayout.vue（追加/改 index）。

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-26-execution-reports.md`.**
