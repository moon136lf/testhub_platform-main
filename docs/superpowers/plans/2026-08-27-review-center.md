# 用例评审与E2E精修（#7）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** #7 评审中心——把 #3 已落地的单用例评审/精修整合成项目级流程页：汇总统计（review_status/feasibility 分布 + 可自动化率）+ 批量精修（同步顺序，容错）+ 批量评审 + 项目级精修报告汇总（建议总表带 case 透传）。不建表、不重写引擎。

**Architecture:** 单 router `reviews.py`（prefix /reviews，4 端点）+ 薄编排 service `ReviewService`（复用 #3 TestCaseService.refine_case / apply_suggestions / update_case / list_cases，不碰 CaseRefiner）。前端 ReviewCenter.vue（统计卡+列表+批量工具栏+报告区）+ api/review.js。

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, pytest, pytest-asyncio, Vue3, Element Plus。

**Spec:** `docs/superpowers/specs/2026-08-25-review-center-design.md`（master 已有）

**测试约定：** `cd backend && PYTHONUTF8=1 python -m pytest`（Windows 须 PYTHONUTF8=1）。全 mock（mock AsyncSession，参照 `tests/test_test_case_service.py` 的 fixture：execute/commit/rollback/refresh 全 mock）。断言真实输出形态。

**Git 约定：** worktree 分支 `worktree-module7-review-center`（基于 master 7a09172）。每 task 末尾 commit，前缀 `feat(review):`/`fix(review):`/`chore(review):`。

**边界：** 不建表不加字段（消费 TestCase 评审 6 字段）；不碰 case_refiner.py / test_case_service.py / schemas/refinement.py。共享文件：`api/__init__.py`（追加 router）、`router/index.js` + `MainLayout.vue`（菜单 /ai/review 死链改指 /reviews）。前端不动其他页面。

---

## File Structure（新建/修改文件总览）

**后端新建：**
- `backend/app/services/review_service.py` — 薄编排：统计聚合 / 批量精修 / 报告汇总 / 批量评审
- `backend/app/schemas/review.py` — 4 端点 request/response schema
- `backend/app/api/v1/reviews.py` — router prefix /reviews
- `backend/tests/test_review_service.py`
- `backend/tests/test_api_reviews.py`

**后端修改：**
- `backend/app/api/__init__.py` — 注册 reviews router（追加 2 行）

**前端新建：**
- `frontend/src/api/review.js` — 封装 /reviews/* + 复用 testCase.js 单用例精修 API

**前端修改：**
- `frontend/src/views/reviews/ReviewCenter.vue` — 新建（评审中心整页）
- `frontend/src/router/index.js` — 加 /reviews 路由
- `frontend/src/layouts/MainLayout.vue` — 菜单 `/ai/review`（死链）改指 `/reviews`

---

## Task 1: ReviewService（统计/批量精修/报告汇总/批量评审）

**Files:**
- Create: `backend/app/services/review_service.py`
- Test: `backend/tests/test_review_service.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_review_service.py`:

```python
"""ReviewService tests (mock db + mock TestCaseService for batch)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

from app.services.review_service import ReviewService


def _mock_rows(values):
    return Mock(all=Mock(return_value=values))


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestGetReviewStats:
    @pytest.mark.asyncio
    async def test_stats_aggregates_and_automation_rate(self, mock_db):
        # 1st query: review_status groups; 2nd: feasibility groups; 3rd: total
        mock_db.execute.side_effect = [
            _mock_rows([("pending", 3), ("passed", 5), ("needs_revision", 2)]),
            _mock_rows([("full", 4), ("partial", 3), ("manual", 3)]),
            Mock(scalar=Mock(return_value=10)),
        ]
        svc = ReviewService(mock_db)
        result = await svc.get_review_stats(str(uuid4()))
        assert result["review_status"] == {"pending": 3, "passed": 5, "needs_revision": 2}
        assert result["feasibility"] == {"full": 4, "partial": 3, "manual": 3}
        # automation rate = (4+3)/10*100 = 70.0
        assert result["automation_rate"] == 70.0
        assert result["total_cases"] == 10

    @pytest.mark.asyncio
    async def test_stats_empty_project(self, mock_db):
        mock_db.execute.side_effect = [
            _mock_rows([]), _mock_rows([]), Mock(scalar=Mock(return_value=0)),
        ]
        svc = ReviewService(mock_db)
        result = await svc.get_review_stats(str(uuid4()))
        assert result["total_cases"] == 0
        assert result["automation_rate"] == 0.0


class TestBatchRefine:
    @pytest.mark.asyncio
    async def test_batch_refine_calls_refine_sequentially_and_collects(self, mock_db):
        svc = ReviewService(mock_db)
        report1 = {"score": 90, "feasibility_level": "full",
                   "suggestions": [{"id": "s1"}, {"id": "s2"}]}
        report2 = {"score": 60, "feasibility_level": "partial", "suggestions": []}
        with patch("app.services.review_service.TestCaseService") as mock_svc_cls:
            inst = mock_svc_cls.return_value
            inst.refine_case = AsyncMock(side_effect=[report1, report2])
            results = await svc.batch_refine(str(uuid4()), ["id-1", "id-2"])
        assert len(results) == 2
        assert results[0] == {"case_id": "id-1", "score": 90,
                              "feasibility_level": "full", "suggestion_count": 2}
        assert results[1] == {"case_id": "id-2", "score": 60,
                              "feasibility_level": "partial", "suggestion_count": 0}
        assert inst.refine_case.call_count == 2

    @pytest.mark.asyncio
    async def test_batch_refine_single_failure_does_not_abort(self, mock_db):
        svc = ReviewService(mock_db)
        with patch("app.services.review_service.TestCaseService") as mock_svc_cls:
            inst = mock_svc_cls.return_value
            inst.refine_case = AsyncMock(side_effect=[
                Exception("LLM down"), {"score": 80, "feasibility_level": "full", "suggestions": []},
            ])
            results = await svc.batch_refine(str(uuid4()), ["bad", "good"])
        assert len(results) == 2
        assert results[0]["error"] == "LLM down"
        assert results[1]["score"] == 80


class TestProjectRefinementReport:
    @pytest.mark.asyncio
    async def test_report_aggregates_suggestions_with_case_passthrough(self, mock_db):
        case_a = MagicMock()
        case_a.id = "aaaaaaaa-0000-0000-0000-000000000001"
        case_a.name = "登录正常流"
        case_a.refinement_report = {
            "score": 90, "refined_at": "2026-08-25T10:00:00",
            "suggestions": [{"id": "s1", "dimension": "断言增强", "issue": "x",
                             "suggestion": "y", "status": "pending"}],
        }
        case_b = MagicMock()
        case_b.id = "bbbbbbbb-0000-0000-0000-000000000002"
        case_b.name = "登出流"
        case_b.refinement_report = None  # not refined -> skipped
        mock_db.execute.return_value = Mock(scalars=Mock(
            return_value=Mock(all=Mock(return_value=[case_a, case_b]))))
        svc = ReviewService(mock_db)
        result = await svc.get_project_refinement_report(str(uuid4()))
        assert result["case_count"] == 1
        assert len(result["suggestions"]) == 1
        s = result["suggestions"][0]
        assert s["case_id"] == case_a.id
        assert s["case_name"] == "登录正常流"
        assert s["id"] == "s1"


class TestBatchUpdateReview:
    @pytest.mark.asyncio
    async def test_batch_review_updates_and_counts(self, mock_db):
        c1, c2, c3 = MagicMock(), MagicMock(), MagicMock()
        mock_db.execute.return_value = Mock(scalars=Mock(
            return_value=Mock(all=Mock(return_value=[c1, c2, c3]))))
        svc = ReviewService(mock_db)
        result = await svc.batch_update_review(
            str(uuid4()), ["1", "2", "3"], "passed", "LGTM")
        assert result == {"success_count": 3, "failure_count": 0}
        assert c1.review_status == "passed"
        assert c1.review_comment == "LGTM"
        assert mock_db.commit.called
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_review_service.py -v`
Expected: FAIL（service 不存在）

- [ ] **Step 3: 实现 ReviewService**

Create `backend/app/services/review_service.py`:

```python
"""Review service: thin orchestration over #3 capabilities.

Project-level stats / batch refine / refinement report aggregation /
batch review update. Reuses TestCaseService (refine_case, apply, update);
does NOT touch CaseRefiner.
"""
import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_case import TestCase
from app.services.test_case_service import TestCaseService

logger = logging.getLogger(__name__)


class ReviewService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_review_stats(self, project_id: str) -> dict:
        """Review status + feasibility distribution + automation rate."""
        pid = UUID(project_id)
        base = TestCase.project_id == pid, TestCase.is_deleted.is_(False)

        status_q = (
            select(TestCase.review_status, func.count())
            .where(and_(*base))
            .group_by(TestCase.review_status)
        )
        feas_q = (
            select(TestCase.feasibility_level, func.count())
            .where(and_(*base))
            .group_by(TestCase.feasibility_level)
        )
        total_q = select(func.count()).select_from(TestCase).where(and_(*base))

        review_status = {r[0] or "pending": r[1]
                         for r in (await self.db.execute(status_q)).all()}
        feasibility = {r[0] or "manual": r[1]
                       for r in (await self.db.execute(feas_q)).all()}
        total = (await self.db.execute(total_q)).scalar() or 0

        auto = feasibility.get("full", 0) + feasibility.get("partial", 0)
        rate = round(auto / total * 100, 1) if total else 0.0
        return {
            "review_status": review_status,
            "feasibility": feasibility,
            "automation_rate": rate,
            "total_cases": total,
        }

    async def batch_refine(self, project_id: str, case_ids: List[str]) -> list:
        """Sequentially refine each case via #3 refine_case. Single failure
        does not abort; the failed entry carries an `error` field."""
        svc = TestCaseService(self.db)
        results = []
        for cid in case_ids:
            try:
                report = await svc.refine_case(cid)
                if report is None:
                    results.append({"case_id": cid, "error": "case not found"})
                    continue
                results.append({
                    "case_id": cid,
                    "score": report.get("score", 0),
                    "feasibility_level": report.get("feasibility_level"),
                    "suggestion_count": len(report.get("suggestions", [])),
                })
            except Exception as e:
                logger.error(f"batch_refine {cid} failed: {e}")
                results.append({"case_id": cid, "error": str(e)})
        return results

    async def get_project_refinement_report(self, project_id: str) -> dict:
        """Aggregate all refinement_report JSONB in the project into a flat
        suggestion table with case_id/case_name passthrough."""
        pid = UUID(project_id)
        q = (
            select(TestCase)
            .where(TestCase.project_id == pid,
                   TestCase.is_deleted.is_(False),
                   TestCase.refinement_report.isnot(None))
            .order_by(TestCase.refined_at.desc())
        )
        cases = (await self.db.execute(q)).scalars().all()
        suggestions = []
        refined_at = None
        for c in cases:
            report = c.refinement_report or {}
            if refined_at is None and report.get("refined_at"):
                refined_at = report.get("refined_at")
            for s in report.get("suggestions", []):
                suggestions.append({
                    **s,
                    "case_id": str(c.id),
                    "case_name": c.name,
                })
        return {
            "case_count": len(cases),
            "refined_at": refined_at,
            "suggestions": suggestions,
        }

    async def batch_update_review(self, project_id: str, case_ids: List[str],
                                  review_status: str,
                                  review_comment: Optional[str] = None) -> dict:
        """Batch update review_status/comment (REVIEW-01 flow). Only touches
        cases in the project."""
        pid = UUID(project_id)
        q = select(TestCase).where(
            TestCase.project_id == pid,
            TestCase.id.in_([UUID(c) for c in case_ids]),
            TestCase.is_deleted.is_(False),
        )
        cases = (await self.db.execute(q)).scalars().all()
        success = failure = 0
        for c in cases:
            try:
                c.review_status = review_status
                c.review_comment = review_comment
                success += 1
            except Exception as e:
                failure += 1
                logger.error(f"batch review {c.id} failed: {e}")
        await self.db.commit()
        return {"success_count": success, "failure_count": failure}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_review_service.py -v`
Expected: PASS（5 tests）

- [ ] **Step 5: 跑全量无回归**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（351 + 5 = 356）

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/review_service.py tests/test_review_service.py
git commit -m "feat(review): ReviewService stats/batch-refine/report/batch-review (W7)"
```

---

## Task 2: schema + reviews API router + 注册

**Files:**
- Create: `backend/app/schemas/review.py`
- Create: `backend/app/api/v1/reviews.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_api_reviews.py`

- [ ] **Step 1: 写 schema**

Create `backend/app/schemas/review.py`:

```python
"""Review center schemas (#7)."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from app.schemas.test_case import REVIEW_STATUSES


class ReviewStatsResponse(BaseModel):
    review_status: Dict[str, int] = {}
    feasibility: Dict[str, int] = {}
    automation_rate: float = 0.0
    total_cases: int = 0


class BatchRefineRequest(BaseModel):
    project_id: str
    case_ids: List[str] = Field(..., min_length=1)


class BatchRefineResultItem(BaseModel):
    case_id: str
    score: Optional[int] = None
    feasibility_level: Optional[str] = None
    suggestion_count: Optional[int] = None
    error: Optional[str] = None


class SuggestionWithCase(BaseModel):
    case_id: str
    case_name: str
    id: Optional[str] = None
    dimension: Optional[str] = None
    severity: Optional[str] = None
    target_step: Optional[int] = None
    issue: Optional[str] = None
    suggestion: Optional[str] = None
    status: Optional[str] = None


class ProjectRefinementReportResponse(BaseModel):
    case_count: int = 0
    refined_at: Optional[str] = None
    suggestions: List[SuggestionWithCase] = []


class BatchReviewRequest(BaseModel):
    project_id: str
    case_ids: List[str] = Field(..., min_length=1)
    review_status: str
    review_comment: Optional[str] = Field(None, max_length=500)

    @field_validator("review_status")
    @classmethod
    def status_valid(cls, v):
        if v not in REVIEW_STATUSES:
            raise ValueError(f"review_status must be one of {REVIEW_STATUSES}")
        return v


class BatchReviewResponse(BaseModel):
    success_count: int = 0
    failure_count: int = 0
```

- [ ] **Step 2: 写失败 API 测试**

Create `backend/tests/test_api_reviews.py`:

```python
"""Reviews API endpoint tests."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app

PID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


def _override(mock_svc):
    from app.api.v1.reviews import get_review_service
    app.dependency_overrides[get_review_service] = lambda: mock_svc


class TestStats:
    def test_stats(self, client):
        svc = MagicMock()
        svc.get_review_stats = AsyncMock(return_value={
            "review_status": {"pending": 3}, "feasibility": {"full": 2},
            "automation_rate": 66.7, "total_cases": 3})
        _override(svc)
        r = client.get(f"/api/v1/reviews/stats?project_id={PID}")
        assert r.status_code == 200
        assert r.json()["automation_rate"] == 66.7


class TestBatchRefine:
    def test_batch_refine(self, client):
        svc = MagicMock()
        svc.batch_refine = AsyncMock(return_value=[
            {"case_id": "c1", "score": 90, "feasibility_level": "full", "suggestion_count": 2}])
        _override(svc)
        r = client.post("/api/v1/reviews/batch-refine",
                        json={"project_id": PID, "case_ids": ["c1"]})
        assert r.status_code == 200
        assert r.json()[0]["score"] == 90

    def test_batch_refine_empty_ids_422(self, client):
        r = client.post("/api/v1/reviews/batch-refine",
                        json={"project_id": PID, "case_ids": []})
        assert r.status_code == 422


class TestReport:
    def test_report(self, client):
        svc = MagicMock()
        svc.get_project_refinement_report = AsyncMock(return_value={
            "case_count": 1, "refined_at": "2026-08-25T10:00:00",
            "suggestions": [{"case_id": "c1", "case_name": "登录", "id": "s1",
                             "dimension": "断言增强", "status": "pending"}]})
        _override(svc)
        r = client.get(f"/api/v1/reviews/refinement-report?project_id={PID}")
        assert r.status_code == 200
        assert r.json()["suggestions"][0]["case_name"] == "登录"


class TestBatchReview:
    def test_batch_review(self, client):
        svc = MagicMock()
        svc.batch_update_review = AsyncMock(return_value={"success_count": 2, "failure_count": 0})
        _override(svc)
        r = client.post("/api/v1/reviews/batch-review",
                        json={"project_id": PID, "case_ids": ["c1", "c2"],
                              "review_status": "passed", "review_comment": "ok"})
        assert r.status_code == 200
        assert r.json()["success_count"] == 2

    def test_batch_review_invalid_status_422(self, client):
        r = client.post("/api/v1/reviews/batch-review",
                        json={"project_id": PID, "case_ids": ["c1"],
                              "review_status": "bogus"})
        assert r.status_code == 422
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_reviews.py -v`
Expected: FAIL（router 未注册 → 404）

- [ ] **Step 4: 实现 router**

Create `backend/app/api/v1/reviews.py`:

```python
"""Reviews API endpoints (prefix /reviews). Project-level review orchestration."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.review_service import ReviewService
from app.schemas.review import (
    ReviewStatsResponse, BatchRefineRequest, BatchRefineResultItem,
    ProjectRefinementReportResponse, BatchReviewRequest, BatchReviewResponse,
)
from typing import List

router = APIRouter()


def get_review_service(db: AsyncSession = Depends(get_db)) -> ReviewService:
    return ReviewService(db)


@router.get("/stats", response_model=ReviewStatsResponse)
async def get_stats(project_id: str = Query(...),
                    svc: ReviewService = Depends(get_review_service)):
    return await svc.get_review_stats(project_id)


@router.post("/batch-refine", response_model=List[BatchRefineResultItem])
async def batch_refine(req: BatchRefineRequest,
                       svc: ReviewService = Depends(get_review_service)):
    return await svc.batch_refine(req.project_id, req.case_ids)


@router.get("/refinement-report", response_model=ProjectRefinementReportResponse)
async def get_refinement_report(project_id: str = Query(...),
                                svc: ReviewService = Depends(get_review_service)):
    return await svc.get_project_refinement_report(project_id)


@router.post("/batch-review", response_model=BatchReviewResponse)
async def batch_review(req: BatchReviewRequest,
                       svc: ReviewService = Depends(get_review_service)):
    return await svc.batch_update_review(req.project_id, req.case_ids,
                                         req.review_status, req.review_comment)
```

- [ ] **Step 5: 注册 router**

Modify `backend/app/api/__init__.py`：

import 行加 `reviews`：
```python
from app.api.v1 import projects, health, elements, sse, ai_case_generation, test_cases, scripts, system, reviews
```

include 区（system 行后）追加：
```python
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_reviews.py -v`
Expected: PASS（6 tests）

- [ ] **Step 7: 路由核对 + 全量**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; rs=sorted(set(r.path for r in app.routes if '/reviews' in getattr(r,'path',''))); [print(p) for p in rs]"`
Expected: 4 条 /reviews/* 路径（stats / batch-refine / refinement-report / batch-review）

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（356 + 6 = 362）

- [ ] **Step 8: Commit**

```bash
cd backend
git add app/schemas/review.py app/api/v1/reviews.py app/api/__init__.py tests/test_api_reviews.py
git commit -m "feat(review): reviews API 4 endpoints + router registration (W7)"
```

---

## Task 3: 前端评审中心页

**Files:**
- Create: `frontend/src/api/review.js`
- Create: `frontend/src/views/reviews/ReviewCenter.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/layouts/MainLayout.vue`

- [ ] **Step 1: 写 api/review.js**

Create `frontend/src/api/review.js`:

```javascript
import axios from './axios'
import { testCaseAPI } from './testCase.js'

export const reviewAPI = {
  getStats(projectId) {
    return axios.get('/reviews/stats', { params: { project_id: projectId } }).then(r => r.data)
  },
  batchRefine(projectId, caseIds) {
    return axios.post('/reviews/batch-refine', { project_id: projectId, case_ids: caseIds }).then(r => r.data)
  },
  getRefinementReport(projectId) {
    return axios.get('/reviews/refinement-report', { params: { project_id: projectId } }).then(r => r.data)
  },
  batchReview(projectId, caseIds, reviewStatus, reviewComment) {
    return axios.post('/reviews/batch-review', {
      project_id: projectId, case_ids: caseIds,
      review_status: reviewStatus, review_comment: reviewComment
    }).then(r => r.data)
  },
  // 单条精修/评审/应用建议复用 #3 API（testCase.js 已有 refineCase/applySuggestions）
  refineCase: (caseId) => testCaseAPI.refineCase(caseId),
  applySuggestions: (caseId) => testCaseAPI.applySuggestions(caseId),
}
```

> 注：实现时先确认 `testCase.js` 中 applySuggestions 方法名（grep `apply`），若命名不同以实际为准（如 `applySuggestion`），review.js 转发对齐实际名。

- [ ] **Step 2: 写 ReviewCenter.vue**

Create `frontend/src/views/reviews/ReviewCenter.vue`（4 区块：筛选 / 汇总统计 / 列表+批量 / 报告区）:

```vue
<template>
  <div class="review-center" v-loading="loading">
    <el-card>
      <template #header><span>用例评审与E2E精修</span></template>

      <!-- ① 筛选 -->
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="projectId" filterable style="width: 220px" @change="loadAll">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="评审状态">
          <el-select v-model="reviewFilter" clearable style="width: 140px" @change="loadCases">
            <el-option label="待评审" value="pending" />
            <el-option label="已通过" value="passed" />
            <el-option label="需修改" value="needs_revision" />
          </el-select>
        </el-form-item>
      </el-form>

      <!-- ② 汇总统计 -->
      <el-row :gutter="16" style="margin-bottom: 16px" v-if="stats">
        <el-col :span="5"><div class="stat"><div class="num">{{ stats.total_cases }}</div><div class="lbl">总用例</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num">{{ stats.review_status.pending || 0 }}</div><div class="lbl">待评审</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num pass">{{ stats.review_status.passed || 0 }}</div><div class="lbl">已通过</div></div></el-col>
        <el-col :span="5"><div class="stat"><div class="num fail">{{ stats.review_status.needs_revision || 0 }}</div><div class="lbl">需修改</div></div></el-col>
        <el-col :span="4"><div class="stat"><div class="num rate">{{ stats.automation_rate }}%</div><div class="lbl">可自动化率</div></div></el-col>
      </el-row>
      <el-progress v-if="stats" :percentage="stats.automation_rate" :stroke-width="8"
        :format="() => `可自动化 ${stats.automation_rate}%`" style="margin-bottom: 16px" />

      <!-- ③ 用例列表 + 批量 -->
      <div style="margin-bottom: 12px">
        <el-button type="primary" size="small" :disabled="!selected.length" :loading="refining"
          @click="onBatchRefine">批量精修（{{ selected.length }}）</el-button>
        <el-button size="small" :disabled="!selected.length" @click="reviewDialog = true">批量评审</el-button>
      </div>
      <el-table :data="cases" border @selection-change="s => selected = s">
        <el-table-column type="selection" width="45" />
        <el-table-column prop="name" label="用例名" min-width="180" show-overflow-tooltip />
        <el-table-column label="评审状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.review_status)">{{ statusLabel(row.review_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="可行性" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.feasibility_level" size="small">{{ row.feasibility_level }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="精修评分" width="90">
          <template #default="{ row }">{{ row.refinement_report?.score ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="onRefine(row)">精修</el-button>
            <el-button link size="small" @click="onApply(row)">应用建议</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- ④ 项目级精修报告 -->
      <el-card shadow="never" style="margin-top: 16px" v-if="report && report.suggestions.length">
        <template #header>
          <div style="display:flex;justify-content:space-between">
            <span>E2E精修报告（{{ report.case_count }} 个用例已精修）</span>
            <el-button type="primary" size="small" @click="onApplyAll">应用全部建议</el-button>
          </div>
        </template>
        <el-table :data="report.suggestions" border>
          <el-table-column prop="case_name" label="用例" width="160" show-overflow-tooltip />
          <el-table-column prop="dimension" label="维度" width="120" />
          <el-table-column prop="issue" label="问题" min-width="180" show-overflow-tooltip />
          <el-table-column prop="suggestion" label="建议" min-width="180" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button v-if="row.status === 'pending'" link type="primary" size="small"
                @click="onApplyOne(row)">确认</el-button>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-card>

    <!-- 批量评审弹窗 -->
    <el-dialog v-model="reviewDialog" title="批量评审" width="420px">
      <el-form label-width="80px">
        <el-form-item label="评审状态">
          <el-select v-model="batchStatus" style="width: 100%">
            <el-option label="通过" value="passed" />
            <el-option label="需修改" value="needs_revision" />
          </el-select>
        </el-form-item>
        <el-form-item label="评审意见">
          <el-input v-model="batchComment" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewDialog = false">取消</el-button>
        <el-button type="primary" @click="onBatchReview">应用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { reviewAPI } from '@/api/review.js'
import { projectAPI } from '@/api/project.js'
import { testCaseAPI } from '@/api/testCase.js'

const loading = ref(false)
const refining = ref(false)
const projects = ref([])
const projectId = ref('')
const reviewFilter = ref('')
const stats = ref(null)
const report = ref(null)
const cases = ref([])
const selected = ref([])
const reviewDialog = ref(false)
const batchStatus = ref('passed')
const batchComment = ref('')

const statusTag = (s) => ({ passed: 'success', needs_revision: 'danger', pending: 'info' }[s] || 'info')
const statusLabel = (s) => ({ passed: '已通过', needs_revision: '需修改', pending: '待评审' }[s] || s || '待评审')

const loadProjects = async () => {
  try {
    const res = await projectAPI.list()
    projects.value = Array.isArray(res) ? res : (res?.items || [])
    if (projects.value.length) { projectId.value = projects.value[0].id; loadAll() }
  } catch (e) { console.error(e) }
}

const loadAll = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const [s, rp] = await Promise.all([
      reviewAPI.getStats(projectId.value),
      reviewAPI.getRefinementReport(projectId.value),
    ])
    stats.value = s
    report.value = rp
    await loadCases()
  } catch (e) { console.error(e) } finally { loading.value = false }
}

// 列表复用 #3 用例列表（带 review_status 筛选 + 全量字段）
// testCaseAPI.list 签名以实际为准（grep 确认）；此处假设 list(params) 返回 {items|数组}
const loadCases = async () => {
  if (!projectId.value) return
  try {
    const params = { project_id: projectId.value, page: 1, page_size: 100 }
    if (reviewFilter.value) params.review_status = reviewFilter.value
    const res = await testCaseAPI.list(params)
    const d = res?.data || res
    cases.value = d.items || d || []
  } catch (e) { console.error(e) }
}

const onRefine = async (row) => {
  loading.value = true
  try {
    await reviewAPI.refineCase(row.id)
    ElMessage.success('精修完成')
    await loadAll()
  } catch (e) { ElMessage.error('精修失败') } finally { loading.value = false }
}

const onBatchRefine = async () => {
  refining.value = true
  try {
    const results = await reviewAPI.batchRefine(projectId.value, selected.value.map(c => c.id))
    const ok = results.filter(r => !r.error).length
    ElMessage.success(`批量精修完成：${ok}/${results.length} 成功`)
    await loadAll()
  } catch (e) { ElMessage.error('批量精修失败') } finally { refining.value = false }
}

const onBatchReview = async () => {
  try {
    const r = await reviewAPI.batchReview(projectId.value, selected.value.map(c => c.id),
      batchStatus.value, batchComment.value || undefined)
    ElMessage.success(`批量评审：${r.success_count} 成功`)
    reviewDialog.value = false
    await loadAll()
  } catch (e) { ElMessage.error('批量评审失败') }
}

const onApply = async (row) => {
  try {
    await reviewAPI.applySuggestions(row.id)
    ElMessage.success('建议已应用')
    await loadAll()
  } catch (e) { ElMessage.error('应用失败') }
}

const onApplyOne = async (row) => {
  try {
    await reviewAPI.applySuggestions(row.case_id, [row.id])
    ElMessage.success('已应用')
    await loadAll()
  } catch (e) { ElMessage.error('应用失败') }
}

const onApplyAll = async () => {
  loading.value = true
  try {
    const caseIds = [...new Set(report.value.suggestions.map(s => s.case_id))]
    for (const cid of caseIds) {
      await reviewAPI.applySuggestions(cid)
    }
    ElMessage.success('全部建议已应用')
    await loadAll()
  } catch (e) { ElMessage.error('应用失败') } finally { loading.value = false }
}

onMounted(loadProjects)
</script>

<style scoped>
.review-center { padding: 20px; }
.stat { text-align: center; border: 1px solid #ebeef5; border-radius: 4px; padding: 12px; }
.stat .num { font-size: 22px; font-weight: 600; }
.stat .pass { color: #67c23a; } .stat .fail { color: #f56c6c; } .stat .rate { color: #409eff; }
.stat .lbl { color: #909399; font-size: 12px; margin-top: 4px; }
</style>
```

> 注：实现时需 grep 确认 `testCase.js` 的 `list` 方法名与返回解包、`applySuggestions` 是否带 ids 参数（`applySuggestions(caseId, ids)` vs `applySuggestions(caseId)`）；`refinement_report?.score` 需确认列表接口返回含该字段（`_to_detail` 已含，见 test_case_service.py:67）。若 list 返回不含 review 字段，改用 detail 接口或在 api 层补充。

- [ ] **Step 3: 路由 + 菜单**

Modify `frontend/src/router/index.js`，children 末尾（reports/:execId 后）加：
```javascript
        {
          path: 'reviews',
          name: 'ReviewCenter',
          component: () => import('@/views/reviews/ReviewCenter.vue'),
          meta: { title: '用例评审与E2E精修' }
        }
```

Modify `frontend/src/layouts/MainLayout.vue`：`<el-menu-item index="/ai/review">用例评审与精修</el-menu-item>` 改为 `<el-menu-item index="/reviews">用例评审与E2E精修</el-menu-item>`（修死链——/ai/review 路由不存在）。

- [ ] **Step 4: 前端构建验证**

Run（worktree 无 node_modules 时用 junction）:
```bash
cd frontend
cmd //c "mklink /J node_modules D:\MoonTest\frontend\node_modules"
node node_modules/vite/bin/vite.js build
cmd //c "rmdir node_modules"
rm -rf dist
```
Expected: 成功（ReviewCenter chunk 正常 emit）

- [ ] **Step 5: Commit**

```bash
cd frontend
git add src/api/review.js src/views/reviews/ReviewCenter.vue src/router/index.js src/layouts/MainLayout.vue
git commit -m "feat(review): ReviewCenter page + routes + menu fix (W7)"
```

---

## Task 4: 全量验证 + 收尾

- [ ] **Step 1: 后端全量**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（351 + 11 = 362）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 路由核对**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; rs=sorted(set(r.path for r in app.routes if '/reviews' in getattr(r,'path',''))); [print(p) for p in rs]"`
Expected: 4 条

- [ ] **Step 4: 更新 TODO_LIST**

Modify `.claude/TODO_LIST.md`：
- 「#7 用例评审与E2E精修」改 P0 完成 + worktree 待合回
- 总体进度计数更新

- [ ] **Step 5: 最终 Commit**

```bash
git add .claude/TODO_LIST.md
git commit -m "chore: update TODO_LIST (#7 review center done) (W7)"
```

---

## Self-Review 记录

**1. Spec 覆盖：**
- 汇总统计（review_status/feasibility GROUP BY + 可自动化率）✓ Task1 get_review_stats
- 批量精修（同步顺序 + 容错单条不中断）✓ Task1 batch_refine（2 测试覆盖容错）
- 项目级精修报告（建议总表带 case_id/name 透传）✓ Task1 get_project_refinement_report
- 批量评审（REVIEW-01 流转 + 限定项目内）✓ Task1 batch_update_review
- 4 端点 /reviews/* ✓ Task2
- 前端 4 区块页 ✓ Task3
- 菜单死链修复 ✓ Task3 Step3
- 复用 #3（refine_case/apply_suggestions/list）不重写 ✓ 全文
- REVIEW-06 不做 ✓ spec §1.3，plan 无涉及
全部覆盖。

**2. 占位符扫描：** Task1/Task2 代码完整。Task3 ReviewCenter.vue 完整给出，2 处「实现时 grep 确认」标注是**防御性指引**（testCase.js 方法名/参数以实际为准），非占位符——给出了确认方法与两种兜底写法。

**3. 类型一致性：** ReviewService 4 方法签名在 service/api/测试/前端链路一致；BatchRefineResultItem 与 batch_refine 返回键（case_id/score/feasibility_level/suggestion_count/error）一致；SuggestionWithCase 与透传键一致；批量评审请求键（project_id/case_ids/review_status/review_comment）schema/router/前端三处一致。

**4. 边界核对：** 只读 TestCase 评审字段（不建表）；复用 TestCaseService 不重写；不碰 case_refiner.py/schemas/refinement.py。共享文件：api/__init__.py（追加）+ router/index.js + MainLayout.vue（死链修复）。

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-27-review-center.md`.**
