# 仪表盘优化（#11）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** #11 仪表盘——把 `Dashboard.vue` 的硬编码 mock 换成真实聚合数据：单聚合端点 `GET /dashboard/overview`（4 统计卡 + 今日 AI 调用/Token + 2 分布饼图 + AI 调用趋势）只读 4 表。

**Architecture:** 单 router `dashboard.py`（prefix /dashboard，1 个 GET 端点）+ 单 service `DashboardService`（聚合 element_repository/test_case/test_point/ai_call_log 4 表）。project_id 可选（None=跳过过滤，「全部项目」）；`days` 仅影响趋势折线。前端只改 Dashboard.vue（mock→API）+ 新建 api/dashboard.js。

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, pytest, pytest-asyncio, Vue3, Element Plus, ECharts。

**Spec:** `docs/superpowers/specs/2026-08-27-dashboard-design.md`

**测试约定：** 后端测试 `cd backend && PYTHONUTF8=1 python -m pytest`（Windows GBK 控制台须 PYTHONUTF8=1）。conftest.py 已 mock sys.path。无 DB 时用 mock AsyncSession；吸取 #6 教训——日期/Row 一律用 MagicMock 带 `.date()` 方法，不用纯 tuple。

**Git 约定：** worktree 分支 `worktree-module11-dashboard`（基于最新 master）。每 task 末尾 commit。message 前缀 `feat(dashboard):`/`chore(dashboard):`。

**边界：** 只读 4 表（element_repository / test_case / test_point / ai_call_log），import 模型不改字段。不碰任何现有 service/router。共享文件：`api/__init__.py`（追加 router 注册 2 行）。前端不动路由/菜单（/dashboard 已存在）。

---

## File Structure（新建/修改文件总览）

**后端新建：**
- `backend/app/services/dashboard_service.py` — 4 表聚合（stats/today/分布/趋势）
- `backend/app/api/v1/dashboard.py` — 单 router prefix /dashboard
- `backend/app/schemas/dashboard.py` — OverviewResponse schema
- `backend/tests/test_dashboard_service.py`
- `backend/tests/test_api_dashboard.py`

**后端修改：**
- `backend/app/api/__init__.py` — 注册 dashboard router

**前端修改：**
- `frontend/src/api/dashboard.js` — 新建，封装 /dashboard/overview
- `frontend/src/views/Dashboard.vue` — mock→真实 API，图表用返回数据

---

## Task 1: DashboardService

**Files:**
- Create: `backend/app/services/dashboard_service.py`
- Test: `backend/tests/test_dashboard_service.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_dashboard_service.py`:

```python
"""DashboardService tests (mock AsyncSession, date rows via MagicMock)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

from app.services.dashboard_service import DashboardService


def _mock_scalar(value):
    return Mock(scalar=Mock(return_value=value))


def _mock_rows(values):
    return Mock(all=Mock(return_value=values))


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


class TestGetOverview:
    @pytest.mark.asyncio
    async def test_overview_all_sections(self, mock_db):
        """8 sequential queries: elem count, case count, automated count,
        point count, today calls, today tokens, elem dist, case dist, trend = 9."""
        today_dt = MagicMock()
        today_dt.date.return_value = MagicMock(isoformat=MagicMock(return_value="2026-08-27"))
        trend_row = MagicMock()
        trend_row.__getitem__ = lambda self, i: [today_dt, 50, 15000][i]
        mock_db.execute.side_effect = [
            _mock_scalar(156),      # element count
            _mock_scalar(243),      # case count
            _mock_scalar(187),      # automated count
            _mock_scalar(324),      # point count
            _mock_scalar(128),      # today ai calls
            _mock_scalar(45672),    # today tokens
            _mock_rows([("button", 30), ("input", 25)]),   # elem dist
            _mock_rows([("functional", 60), ("api", 40)]), # case dist
            _mock_rows([trend_row]),                        # trend
        ]
        svc = DashboardService(mock_db)
        result = await svc.get_overview(None, days=7)
        assert result["stats"] == {"element_count": 156, "case_count": 243,
                                   "automated_count": 187, "point_count": 324}
        assert result["today"] == {"ai_calls": 128, "tokens_used": 45672}
        assert result["element_distribution"] == [{"type": "button", "count": 30},
                                                   {"type": "input", "count": 25}]
        assert result["case_distribution"] == [{"type": "functional", "count": 60},
                                                {"type": "api", "count": 40}]
        assert result["ai_trend"][0]["date"] == "2026-08-27"
        assert result["ai_trend"][0]["call_count"] == 50
        assert result["ai_trend"][0]["tokens"] == 15000

    @pytest.mark.asyncio
    async def test_overview_none_values_default_zero(self, mock_db):
        mock_db.execute.side_effect = [
            _mock_scalar(None), _mock_scalar(None), _mock_scalar(None), _mock_scalar(None),
            _mock_scalar(None), _mock_scalar(None),
            _mock_rows([]), _mock_rows([]), _mock_rows([]),
        ]
        svc = DashboardService(mock_db)
        result = await svc.get_overview(None)
        assert result["stats"] == {"element_count": 0, "case_count": 0,
                                   "automated_count": 0, "point_count": 0}
        assert result["today"] == {"ai_calls": 0, "tokens_used": 0}
        assert result["element_distribution"] == []
        assert result["ai_trend"] == []

    @pytest.mark.asyncio
    async def test_overview_with_project_filter(self, mock_db):
        """project_id passed -> UUID applied (queries still run, shape unchanged)."""
        mock_db.execute.side_effect = [
            _mock_scalar(1), _mock_scalar(2), _mock_scalar(3), _mock_scalar(4),
            _mock_scalar(5), _mock_scalar(6),
            _mock_rows([]), _mock_rows([]), _mock_rows([]),
        ]
        svc = DashboardService(mock_db)
        result = await svc.get_overview(str(uuid4()))
        assert result["stats"]["element_count"] == 1
        assert len(mock_db.execute.call_args_list) == 9
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_dashboard_service.py -v`
Expected: FAIL（service 不存在）

- [ ] **Step 3: 实现 DashboardService**

Create `backend/app/services/dashboard_service.py`:

```python
"""Dashboard service: aggregate overview over element/case/point/ai_call_log tables.

Read-only. project_id=None means "all projects" (skip the filter).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.element import ElementRepository
from app.models.test_case import TestCase, TestPoint
from app.models.execution import AICallLog

logger = logging.getLogger(__name__)


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(self, project_id: Optional[str] = None, days: int = 7) -> dict:
        pid = UUID(project_id) if project_id else None
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        since = now - timedelta(days=days)

        def scope(q, col):
            """Apply optional project filter to a query on the given column."""
            return q.where(col == pid) if pid else q

        # ---- 4 stat cards (current totals, unaffected by days) ----
        elem_q = scope(select(func.count()).select_from(ElementRepository)
                       .where(ElementRepository.status == "active"),
                       ElementRepository.project_id)
        case_q = scope(select(func.count()).select_from(TestCase)
                       .where(TestCase.is_deleted.is_(False)),
                       TestCase.project_id)
        auto_q = scope(select(func.count()).select_from(TestCase)
                       .where(TestCase.is_deleted.is_(False),
                              TestCase.automation_status == "automated"),
                       TestCase.project_id)
        point_q = scope(select(func.count()).select_from(TestPoint),
                        TestPoint.project_id)

        elem_count = (await self.db.execute(elem_q)).scalar() or 0
        case_count = (await self.db.execute(case_q)).scalar() or 0
        auto_count = (await self.db.execute(auto_q)).scalar() or 0
        point_count = (await self.db.execute(point_q)).scalar() or 0

        # ---- today AI calls / tokens (UTC midnight boundary) ----
        calls_q = scope(select(func.count()).select_from(AICallLog)
                        .where(AICallLog.created_at >= today_start),
                        AICallLog.project_id)
        tokens_q = scope(select(func.coalesce(func.sum(AICallLog.tokens_used), 0))
                         .select_from(AICallLog)
                         .where(AICallLog.created_at >= today_start),
                         AICallLog.project_id)
        ai_calls = (await self.db.execute(calls_q)).scalar() or 0
        tokens_used = (await self.db.execute(tokens_q)).scalar() or 0

        # ---- distributions ----
        elem_dist_q = scope(select(ElementRepository.element_type, func.count())
                            .where(ElementRepository.status == "active")
                            .group_by(ElementRepository.element_type),
                            ElementRepository.project_id)
        case_dist_q = scope(select(TestCase.case_type, func.count())
                            .where(TestCase.is_deleted.is_(False))
                            .group_by(TestCase.case_type),
                            TestCase.project_id)
        elem_dist = [{"type": r[0] or "other", "count": r[1]}
                     for r in (await self.db.execute(elem_dist_q)).all()]
        case_dist = [{"type": r[0] or "functional", "count": r[1]}
                     for r in (await self.db.execute(case_dist_q)).all()]

        # ---- AI trend (only section affected by days) ----
        trend_q = scope(
            select(
                func.date_trunc("day", AICallLog.created_at).label("d"),
                func.count().label("cnt"),
                func.coalesce(func.sum(AICallLog.tokens_used), 0).label("tokens"),
            )
            .where(AICallLog.created_at >= since)
            .group_by("d").order_by("d"),
            AICallLog.project_id,
        )
        trend = [
            {
                "date": str(r[0].date()) if r[0] else "",
                "call_count": r[1],
                "tokens": r[2],
            }
            for r in (await self.db.execute(trend_q)).all()
        ]

        return {
            "stats": {
                "element_count": elem_count,
                "case_count": case_count,
                "automated_count": auto_count,
                "point_count": point_count,
            },
            "today": {"ai_calls": ai_calls, "tokens_used": tokens_used},
            "element_distribution": elem_dist,
            "case_distribution": case_dist,
            "ai_trend": trend,
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_dashboard_service.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: 跑全量无回归**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/dashboard_service.py tests/test_dashboard_service.py
git commit -m "feat(dashboard): DashboardService 4-table aggregation (W11)"
```

---

## Task 2: overview schema + API router + 注册

**Files:**
- Create: `backend/app/schemas/dashboard.py`
- Create: `backend/app/api/v1/dashboard.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_api_dashboard.py`

- [ ] **Step 1: 写 schema**

Create `backend/app/schemas/dashboard.py`:

```python
"""Dashboard schemas."""
from typing import List, Optional
from pydantic import BaseModel


class DashboardStats(BaseModel):
    element_count: int = 0
    case_count: int = 0
    automated_count: int = 0
    point_count: int = 0


class DashboardToday(BaseModel):
    ai_calls: int = 0
    tokens_used: int = 0


class DistributionItem(BaseModel):
    type: str
    count: int = 0


class TrendItem(BaseModel):
    date: str
    call_count: int = 0
    tokens: int = 0


class OverviewResponse(BaseModel):
    stats: DashboardStats
    today: DashboardToday
    element_distribution: List[DistributionItem] = []
    case_distribution: List[DistributionItem] = []
    ai_trend: List[TrendItem] = []
```

- [ ] **Step 2: 写失败 API 测试**

Create `backend/tests/test_api_dashboard.py`:

```python
"""Dashboard API endpoint tests."""
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _fake_overview():
    return {
        "stats": {"element_count": 1, "case_count": 2, "automated_count": 3, "point_count": 4},
        "today": {"ai_calls": 5, "tokens_used": 6},
        "element_distribution": [{"type": "button", "count": 1}],
        "case_distribution": [{"type": "functional", "count": 2}],
        "ai_trend": [{"date": "2026-08-27", "call_count": 1, "tokens": 100}],
    }


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


class TestOverview:
    def test_overview_returns_all_sections(self, client):
        svc = MagicMock()
        svc.get_overview = MagicMock(return_value=_fake_overview())
        from app.api.v1.dashboard import get_dashboard_service
        app.dependency_overrides[get_dashboard_service] = lambda: svc
        r = client.get("/api/v1/dashboard/overview")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["stats"]["element_count"] == 1
        assert data["today"]["ai_calls"] == 5
        assert data["element_distribution"][0]["type"] == "button"
        assert data["ai_trend"][0]["tokens"] == 100

    def test_overview_passes_query_params(self, client):
        svc = MagicMock()
        svc.get_overview = MagicMock(return_value=_fake_overview())
        from app.api.v1.dashboard import get_dashboard_service
        app.dependency_overrides[get_dashboard_service] = lambda: svc
        r = client.get("/api/v1/dashboard/overview",
                       params={"project_id": "00000000-0000-0000-0000-000000000001", "days": 30})
        assert r.status_code == 200
        svc.get_overview.assert_called_once_with("00000000-0000-0000-0000-000000000001", days=30)

    def test_overview_days_out_of_range_422(self, client):
        r = client.get("/api/v1/dashboard/overview", params={"days": 999})
        assert r.status_code == 422
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_dashboard.py -v`
Expected: FAIL（router 未注册，404）

- [ ] **Step 4: 实现 router**

Create `backend/app/api/v1/dashboard.py`:

```python
"""Dashboard API endpoints (prefix /dashboard). Read-only 4-table aggregation."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.dashboard_service import DashboardService
from app.schemas.dashboard import OverviewResponse

router = APIRouter()


def get_dashboard_service(db: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(db)


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    project_id: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
    svc: DashboardService = Depends(get_dashboard_service),
):
    result = await svc.get_overview(project_id, days=days)
    return result
```

- [ ] **Step 5: 注册 router**

Modify `backend/app/api/__init__.py`：

import 行改为：
```python
from app.api.v1 import projects, health, elements, sse, ai_case_generation, test_cases, scripts, system, dashboard
```

include 区末尾（system 行后）追加：
```python
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_dashboard.py -v`
Expected: PASS（3 tests）

- [ ] **Step 7: 路由核对 + 全量**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; rs=[r.path for r in app.routes if '/dashboard' in getattr(r,'path','')]; [print(r) for r in sorted(set(rs))]"`
Expected: `/api/v1/dashboard/overview`

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

- [ ] **Step 8: Commit**

```bash
cd backend
git add app/schemas/dashboard.py app/api/v1/dashboard.py app/api/__init__.py tests/test_api_dashboard.py
git commit -m "feat(dashboard): /dashboard/overview API + router registration (W11)"
```

---

## Task 3: 前端接线（api/dashboard.js + Dashboard.vue 改真实数据）

**Files:**
- Create: `frontend/src/api/dashboard.js`
- Modify: `frontend/src/views/Dashboard.vue`

- [ ] **Step 1: 写 api/dashboard.js**

Create `frontend/src/api/dashboard.js`:

```javascript
import axios from './axios'

export const dashboardAPI = {
  getOverview(params) {
    return axios.get('/dashboard/overview', { params }).then(r => r.data)
  }
}
```

- [ ] **Step 2: 改 Dashboard.vue script（mock→API）**

Modify `frontend/src/views/Dashboard.vue` `<script setup>`：

替换 import 区（加 axios + dashboardAPI，去掉无用的）：
```javascript
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { dashboardAPI } from '@/api/dashboard.js'
import { projectAPI } from '@/api/project.js'
```

替换数据初始化（projects 加载 + stats 保持结构）：
```javascript
const selectedProject = ref('')
const timeRange = ref('7')
const projects = ref([])

const stats = ref({
  elementCount: 0,
  caseCount: 0,
  automatedCount: 0,
  pointCount: 0,
  todayAICalls: 0,
  todayTokens: 0
})

const elementDist = ref([])
const caseDist = ref([])
const aiTrend = ref([])
```

替换 `refreshData` 与新增 `loadProjects`：
```javascript
const loadProjects = async () => {
  try {
    const res = await projectAPI.list()
    projects.value = res.data || res || []
  } catch (e) { console.error(e) }
}

const refreshData = async () => {
  loading.value = true
  try {
    const res = await dashboardAPI.getOverview({
      project_id: selectedProject.value || undefined,
      days: Number(timeRange.value) || 7
    })
    const d = res.data || res
    stats.value = {
      elementCount: d.stats.element_count,
      caseCount: d.stats.case_count,
      automatedCount: d.stats.automated_count,
      pointCount: d.stats.point_count,
      todayAICalls: d.today.ai_calls,
      todayTokens: d.today.tokens_used
    }
    elementDist.value = d.element_distribution || []
    caseDist.value = d.case_distribution || []
    aiTrend.value = d.ai_trend || []
    await nextTick()
    initCharts()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}
```

注意 `loading` ref 需新增：`const loading = ref(false)`（模板里可给最外层 div 加 `v-loading="loading"`）。

替换 `initCharts` 中三处 mock data 为响应数据：
- 元素饼图 series data 改为：`data: elementDist.value.map(i => ({ value: i.count, name: i.type }))`
- 用例饼图 series data 改为：`data: caseDist.value.map(i => ({ value: i.count, name: i.type }))`
- 趋势图 xAxis 改为：`data: aiTrend.value.map(i => i.date)`；两个 series 的 data 改为：`data: aiTrend.value.map(i => i.call_count)` 与 `data: aiTrend.value.map(i => i.tokens)`

替换 `onMounted` 与新增清理：
```javascript
const handleResize = () => {
  elementChart?.resize()
  caseChart?.resize()
  trendChart?.resize()
}

onMounted(async () => {
  await loadProjects()
  await refreshData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  elementChart?.dispose()
  caseChart?.dispose()
  trendChart?.dispose()
})
```

图表 init 前先 dispose 旧实例（`initCharts` 开头加 `elementChart?.dispose(); caseChart?.dispose(); trendChart?.dispose()`），避免重复 init 警告。

- [ ] **Step 3: 前端构建验证**

Run: `cd frontend && npm run build`
Expected: 成功（Dashboard chunk 正常 emit）

> 注：worktree 无 node_modules 时，用 junction 复用主仓：`cmd //c "mklink /J node_modules D:\MoonTest\frontend\node_modules"`，构建后 `cmd //c "rmdir node_modules"` 清理（不删主仓文件）。

- [ ] **Step 4: Commit**

```bash
cd frontend
git add src/api/dashboard.js src/views/Dashboard.vue
git commit -m "feat(dashboard): Dashboard.vue wire real /dashboard/overview API (W11)"
```

---

## Task 4: 全量验证 + 收尾

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（master 343 + #11 新增 6 = 349）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 路由核对**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; rs=[r.path for r in app.routes if '/dashboard' in getattr(r,'path','')]; [print(r) for r in sorted(set(rs))]"`
Expected: `/api/v1/dashboard/overview` 1 条

- [ ] **Step 4: 更新 TODO_LIST**

Modify `.claude/TODO_LIST.md`：
- 「#11 仪表盘优化」改为 P0 完成 + worktree 待合回
- 总体进度「已完成」计数更新

- [ ] **Step 5: 最终 Commit**

```bash
git add .claude/TODO_LIST.md
git commit -m "chore: update TODO_LIST (#11 dashboard done) (W11)"
```

---

## Self-Review 记录

**1. Spec 覆盖：**
- 单聚合端点 /dashboard/overview ✓ Task2
- 4 统计卡（active 元素 / !deleted 用例 / automated / test_point）✓ Task1
- 今日 AI 调用 + Token（UTC 0 点）✓ Task1
- 2 分布（element_type / case_type group by）✓ Task1
- 趋势（date_trunc，仅 days 影响）✓ Task1
- project_id 可选跳过过滤 ✓ Task1 scope() helper
- schema（OverviewResponse）✓ Task2 Step1
- 前端接线（api/dashboard.js + Dashboard.vue mock→API）✓ Task3
- 响应式刷新（切换项目/时间/刷新重拉）✓ Task3 Step2
- 注册 router ✓ Task2 Step5
全部覆盖。

**2. 占位符扫描：** 无 TBD/TODO。Task3 的 Dashboard.vue 改动给出逐段代码与精确改点。

**3. 类型一致性：** `DashboardService.get_overview(project_id, days)` 在 service/api/测试/前端调用链一致；响应键 stats/today/element_distribution/case_distribution/ai_trend 在 schema/service/前端解构一致；`dashboardAPI.getOverview(params)` 与前端调用一致。

**4. 边界核对：** 只读 4 表（import 不改字段）；不碰现有 service/router。共享文件仅 api/__init__.py（追加 2 行）。前端不动路由/菜单。

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-27-dashboard.md`.**
