# 用例生成记录（case_batch 两级用例管理）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用例管理页改为"生成记录列表→点击查看批内用例"两级结构；白盒/AI 生成用例按命名规范自动归批；查看页提供评审与转脚本入口，转完脚本自动入脚本库并按记录名命名。

**Architecture:** 新增 `case_batch` 表（生成批次），`test_case` 加 `batch_id` 列；三个生成点（白盒功能用例生成、AI 用例生成、手工新建）落库时挂批次；新增 batches CRUD API；Cases.vue 改为记录列表，CaseDetail.vue 承接批内用例+评审/转脚本入口；脚本库命名取所属批次名。

**Tech Stack:** FastAPI + SQLAlchemy(async) + Pydantic / Vue3 + Element Plus / PostgreSQL 迁移 SQL（幂等，仿 `migrations/add_whitescan_tables.sql` 风格）

**用户已确认的决策：**
- AI 需求命名取需求文本前 50 字符
- 历史无批次用例直接删除（执行前统计数量给用户确认）
- 记录列表操作列：[查看] [删除]

---

## 命名规范（T1 纯函数实现）

| 来源 | batch_type | 模板 |
|---|---|---|
| 白盒-接口回归 | whitescan_api | `白盒测试生成接口回归用例YYYYMMDDHHmmss` |
| 白盒-UI回归 | whitescan_ui | `白盒测试生成UI回归用例YYYYMMDDHHmmss` |
| AI 需求生成 | ai_generate | `{需求名前50字}生成的用例YYYYMMDDHHmmss` |
| 手工 | manual | `手工创建用例YYYYMMDDHHmmss` |
| 转脚本批次（T4） | — | `{所属batch_name}-自动化脚本HHmmss`（script_asset.name） |

---

### Task 1: case_batch 模型 + 迁移 + 命名纯函数

**Files:**
- Create: `backend/app/models/case_batch.py`
- Modify: `backend/app/models/__init__.py`（导出 CaseBatch）
- Modify: `backend/app/models/test_case.py`（TestCase 加 batch_id 列）
- Create: `backend/migrations/add_case_batch_table.sql`
- Create: `backend/app/services/batch_naming.py`（命名纯函数）
- Test: `backend/tests/test_batch_naming.py`

- [ ] **Step 1: 写命名函数失败测试**

```python
"""batch_naming 纯函数测试（T1）"""
from datetime import datetime
from app.services.batch_naming import build_batch_name, truncate_requirement


class TestBuildBatchName:
    def test_whitescan_api(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("whitescan_api", ts) == "白盒测试生成接口回归用例20260902143025"

    def test_whitescan_ui(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("whitescan_ui", ts) == "白盒测试生成UI回归用例20260902143025"

    def test_ai_generate_truncates_50(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        req = "登" * 60  # 60 字
        name = build_batch_name("ai_generate", ts, requirement=req)
        assert name == "登" * 50 + "生成的用例20260902143025"

    def test_ai_generate_short_req(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("ai_generate", ts, requirement="用户登录") == "用户登录生成的用例20260902143025"

    def test_ai_generate_empty_req_fallback(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("ai_generate", ts, requirement="") == "未命名需求生成的用例20260902143025"

    def test_manual(self):
        ts = datetime(2026, 9, 2, 14, 30, 25)
        assert build_batch_name("manual", ts) == "手工创建用例20260902143025"

    def test_invalid_type_raises(self):
        import pytest
        with pytest.raises(ValueError):
            build_batch_name("bogus", datetime.now())


class TestTruncateRequirement:
    def test_truncate_50(self):
        assert truncate_requirement("a" * 80) == "a" * 50

    def test_none(self):
        assert truncate_requirement(None) == "未命名需求"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_batch_naming.py -q`
Expected: FAIL（ModuleNotFoundError: batch_naming）

- [ ] **Step 3: 实现 batch_naming.py**

```python
"""生成批次命名纯函数（命名规范见 T1 计划头部表格）。"""
from datetime import datetime

VALID_TYPES = {"whitescan_api", "whitescan_ui", "ai_generate", "manual"}
_TS_FMT = "%Y%m%d%H%M%S"
_REQ_MAX = 50

_TEMPLATES = {
    "whitescan_api": "白盒测试生成接口回归用例{ts}",
    "whitescan_ui": "白盒测试生成UI回归用例{ts}",
    "ai_generate": "{req}生成的用例{ts}",
    "manual": "手工创建用例{ts}",
}


def truncate_requirement(text: str | None) -> str:
    """需求名截断至 50 字符；空/None 用兜底名。"""
    if not text or not str(text).strip():
        return "未命名需求"
    return str(text).strip()[:_REQ_MAX]


def build_batch_name(batch_type: str, ts: datetime, requirement: str | None = None) -> str:
    if batch_type not in VALID_TYPES:
        raise ValueError(f"invalid batch_type: {batch_type}")
    template = _TEMPLATES[batch_type]
    return template.format(ts=ts.strftime(_TS_FMT), req=truncate_requirement(requirement))
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_batch_naming.py -q`
Expected: 8 passed

- [ ] **Step 5: CaseBatch 模型 + TestCase.batch_id**

`backend/app/models/case_batch.py`:

```python
"""CaseBatch — 用例生成批次（用例管理记录层）。"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class CaseBatch(Base):
    __tablename__ = "case_batch"
    __table_args__ = (
        UniqueConstraint("project_id", "batch_name", name="uq_case_batch_project_name"),
        Index("idx_case_batch_project", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"),
                        nullable=False)
    batch_name = Column(String(200), nullable=False)
    batch_type = Column(String(20), nullable=False)  # whitescan_api/whitescan_ui/ai_generate/manual
    source_id = Column(UUID(as_uuid=True), nullable=True)  # scan_id / generation_session_id
    case_count = Column(Integer, default=0)
    created_at = Column(datetime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "batch_name": self.batch_name,
            "batch_type": self.batch_type,
            "source_id": str(self.source_id) if self.source_id else None,
            "case_count": self.case_count or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
```

`backend/app/models/test_case.py` 在 TestCase 类内加列（放在 source_issue_id 之后）：

```python
    # 批次归属（用例管理记录层, case_batch.id）; NULL=历史遗留(将被清理)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("case_batch.id", ondelete="SET NULL"), nullable=True)
```

`backend/app/models/__init__.py` 加导出（仿现有 import 行）：

```python
from app.models.case_batch import CaseBatch
```

- [ ] **Step 6: 迁移 SQL**

`backend/migrations/add_case_batch_table.sql`（幂等，仿 add_whitescan_tables.sql）：

```sql
-- 用例生成批次 (case_batch) + test_case.batch_id. Idempotent.
CREATE TABLE IF NOT EXISTS case_batch (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    batch_name VARCHAR(200) NOT NULL,
    batch_type VARCHAR(20) NOT NULL,
    source_id UUID,
    case_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_case_batch_project_name UNIQUE (project_id, batch_name)
);
CREATE INDEX IF NOT EXISTS idx_case_batch_project ON case_batch(project_id);

ALTER TABLE test_case ADD COLUMN IF NOT EXISTS batch_id UUID REFERENCES case_batch(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_test_case_batch ON test_case(batch_id);
```

- [ ] **Step 7: 验证模型可导入 + 全量无回归**

Run: `cd backend && python -c "from app.models import CaseBatch; print('ok')" && python -m pytest tests/test_batch_naming.py -q`
Expected: ok / 8 passed

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/case_batch.py backend/app/models/__init__.py backend/app/models/test_case.py backend/app/services/batch_naming.py backend/tests/test_batch_naming.py backend/migrations/add_case_batch_table.sql
git commit -m "feat(cases): case_batch model + naming function (#case-batch T1)"
```

---

### Task 2: 三个生成点挂批次 + 存量清理 + batches API

**Files:**
- Create: `backend/app/services/case_batch_service.py`（建批次/删批次/列表）
- Modify: `backend/app/services/functional_case_generator.py`（generate_from_repo 建 2 条批次）
- Modify: `backend/app/api/v1/whitescan.py`（generate-cases 传 scan_id 建 UI 批）
- Modify: `backend/app/tasks/ai_case_tasks.py`（generate_test_cases_task 建批次）
- Modify: `backend/app/api/v1/test_cases.py`（batches 列表/详情/删除端点）
- Modify: `backend/app/api/v1/projects.py` 不动（批次随项目级联删，靠 FK）
- Test: `backend/tests/test_case_batch_service.py`

- [ ] **Step 1: 写 CaseBatchService 失败测试**

```python
"""CaseBatchService 测试（mock db，真实逻辑）"""
import asyncio
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from app.services.case_batch_service import CaseBatchService


def _db():
    db = MagicMock()
    db.added = []

    async def _flush():
        pass

    async def _refresh(obj):
        obj.id = "fake-uuid"

    db.flush = _flush
    db.refresh = _refresh
    db.add = lambda o: db.added.append(o)
    return db


class TestCreateBatch:
    def test_create_whitescan_api_batch(self):
        db = _db()
        svc = CaseBatchService(db)
        batch = asyncio.run(svc.create_batch(
            project_id="p1", batch_type="whitescan_api",
            ts=datetime(2026, 9, 2, 14, 30, 25), source_id="scan-1"))
        assert db.added == [batch]
        assert batch.batch_name == "白盒测试生成接口回归用例20260902143025"
        assert batch.batch_type == "whitescan_api"
        assert batch.source_id == "scan-1"

    def test_create_ai_batch_with_requirement(self):
        db = _db()
        svc = CaseBatchService(db)
        batch = asyncio.run(svc.create_batch(
            project_id="p1", batch_type="ai_generate",
            ts=datetime(2026, 9, 2, 14, 30, 25), requirement="用户登录功能需求说明"))
        assert batch.batch_name == "用户登录功能需求说明生成的用例20260902143025"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_case_batch_service.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 CaseBatchService**

```python
"""生成批次服务: 建批次 / 批内用例挂 batch_id / 删批次(软删级联) / 存量清理."""
import logging
from datetime import datetime

from app.models.case_batch import CaseBatch
from app.services.batch_naming import build_batch_name

logger = logging.getLogger(__name__)


class CaseBatchService:
    def __init__(self, db):
        self.db = db

    async def create_batch(self, project_id: str, batch_type: str,
                           ts: datetime | None = None,
                           source_id: str | None = None,
                           requirement: str | None = None) -> CaseBatch:
        """建批次记录。batch_name 按命名规范生成；同项目重名(同秒重试)时
        追加 '-2' 后缀兜底。"""
        ts = ts or datetime.now()
        name = build_batch_name(batch_type, ts, requirement)
        existing = await self._name_exists(project_id, name)
        if existing:
            name = f"{name}-2"[:200]
        batch = CaseBatch(
            project_id=project_id, batch_name=name, batch_type=batch_type,
            source_id=source_id, case_count=0,
        )
        self.db.add(batch)
        await self.db.flush()
        return batch

    async def _name_exists(self, project_id, name) -> bool:
        from sqlalchemy import select
        r = await self.db.execute(
            select(CaseBatch.id).where(CaseBatch.project_id == project_id,
                                       CaseBatch.batch_name == name).limit(1))
        return r.scalar_one_or_none() is not None

    async def update_case_count(self, batch_id, delta: int):
        """生成完成后回填批次用例数。"""
        batch = await self.db.get(CaseBatch, batch_id)
        if batch:
            batch.case_count = (batch.case_count or 0) + delta
            await self.db.flush()
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_case_batch_service.py -q`
Expected: 2 passed

- [ ] **Step 5: functional_case_generator 挂批次**

修改 `generate_from_repo` 签名与开头（`backend/app/services/functional_case_generator.py:32-54`）：

```python
    async def generate_from_repo(self, project_id: str, repo_path: str,
                                 source_id: str | None = None) -> dict:
        menus = self.analyzer.analyze_frontend(repo_path)
        apis = self.analyze_and_filter(apis_source := self.analyzer.analyze_backend(repo_path))
        from app.services.case_batch_service import CaseBatchService
        batch_svc = CaseBatchService(self.db)
        ui_batch = await batch_svc.create_batch(project_id, "whitescan_ui", source_id=source_id)
        api_batch = await batch_svc.create_batch(project_id, "whitescan_api", source_id=source_id)
        generated, failed = 0, 0

        # 菜单批
        for i in range(0, len(menus), MENU_BATCH_SIZE):
            batch = menus[i:i + MENU_BATCH_SIZE]
            ok, n = await self._gen_menu_batch(project_id, batch, batch_id=ui_batch.id)
            ...
```

同时 `_call_and_save` 加 `batch_id=None` 参数，TestCase(...) 加 `batch_id=batch_id`；菜单/API 批循环结束后分别回填：

```python
        await batch_svc.update_case_count(ui_batch.id, ui_generated)
        await batch_svc.update_case_count(api_batch.id, api_generated)
```

（generated 计数按 UI/API 分别累计——把 `generate_from_repo` 中两段循环的 n 分别存入 `ui_generated`/`api_generated`。）

注意：上面伪代码中 `analyze_and_filter` 一行不存在，保持现有 `apis = self.analyzer.analyze_backend(repo_path)` 不变，噪音过滤已在 `_gen_api_batch` 内。

- [ ] **Step 6: whitescan 端点传 source_id**

`backend/app/api/v1/whitescan.py:106` 改：

```python
        result = await gen.generate_from_repo(project_id, repo_path, source_id=scan_id)
```

- [ ] **Step 7: AI 生成任务挂批次**

`backend/app/tasks/ai_case_tasks.py` `_generate_test_cases_async`（~line 451 起）：函数开头（SSE 初始化后）建批次：

```python
    from app.services.case_batch_service import CaseBatchService
    batch_svc = CaseBatchService(db)
    batch = await batch_svc.create_batch(project_id, "ai_generate",
                                         requirement=doc_content[:50] if doc_content else None)
    batch_id = batch.id
    batch_generated = 0
```

doc_content 来源：任务签名里没有——从函数开头已有的输入校验区读取（该任务参数含 point_ids；需求文本在 generation_session 里）。在函数开头加查询：

```python
    from app.models.generation import GenerationSession
    r = await db.execute(select(GenerationSession).where(
        GenerationSession.project_id == UUID(project_id)).order_by(
        GenerationSession.created_at.desc()).limit(1))
    gs = r.scalar_one_or_none()
    req_text = (gs.document_content or "")[:50] if gs else None
```

生成保存处（~line 561 `TestCase(` 构造）加 `batch_id=batch_id`，`success_count += 1` 处同步 `batch_generated += 1`；任务完成消息前回填 `await batch_svc.update_case_count(batch_id, batch_generated)`。

- [ ] **Step 8: batches API（列表/批内用例/删除）**

`backend/app/api/v1/test_cases.py` 加三个端点（注意路由顺序：必须放在 `GET /{case_id}` 之前，否则 batches 被吃掉）：

```python
@router.get("/batches")
async def list_case_batches(
    project_id: UUID = Query(...),
    batch_type: str | None = Query(None, pattern="^(whitescan_api|whitescan_ui|ai_generate|manual)$"),
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """生成记录列表（用例管理记录层）。"""
    from app.models.case_batch import CaseBatch
    q = select(CaseBatch).where(CaseBatch.project_id == project_id)
    if batch_type:
        q = q.where(CaseBatch.batch_type == batch_type)
    if keyword:
        q = q.where(CaseBatch.batch_name.ilike(f"%{keyword}%"))
    total_r = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_r.scalar() or 0
    q = q.order_by(CaseBatch.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()
    return {"code": 0, "data": {"items": [b.to_dict() for b in rows],
                                "total": total, "page": page, "page_size": page_size}}


@router.get("/batches/{batch_id}/cases")
async def list_batch_cases(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """批内用例列表（查看页数据源）。"""
    r = await db.execute(
        select(TestCase).where(TestCase.batch_id == batch_id,
                               TestCase.is_deleted.is_(False))
        .order_by(TestCase.created_at))
    cases = r.scalars().all()
    return {"code": 0, "data": [c.to_dict() for c in cases]}


@router.delete("/batches/{batch_id}", status_code=204)
async def delete_case_batch(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """删批次：软删批内全部用例 + 批次记录本身软删不可行(无列)→物理删批次行,
    用例保留软删。"""
    from app.models.case_batch import CaseBatch
    batch = await db.get(CaseBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    await db.execute(update(TestCase).where(TestCase.batch_id == batch_id)
                     .values(is_deleted=True))
    await db.delete(batch)
    await db.commit()
```

文件头部若缺 import 补：`from sqlalchemy import select, update, func`、`from fastapi import Query`、`from app.models.test_case import TestCase`（确认现有 import 后仅补缺）。

- [ ] **Step 9: API 测试**

在 `backend/tests/test_case_batch_service.py` 追加（mock db 风格，只测 service 层可测部分——端点逻辑薄，端到端由 T3 手工验证）：

```python
class TestUpdateCaseCount:
    def test_increment(self):
        db = _db()
        batch = MagicMock()
        batch.case_count = 5

        async def _get(cls, bid):
            return batch

        db.get = _get
        svc = CaseBatchService(db)
        asyncio.run(svc.update_case_count("b1", 3))
        assert batch.case_count == 8
```

Run: `cd backend && python -m pytest tests/test_case_batch_service.py -q`
Expected: 3 passed

- [ ] **Step 10: 存量清理脚本（跑前需用户确认数量）**

Create: `backend/migrations/cleanup_legacy_cases.sql`（**不自动执行**，先在 DB 查数量给用户确认）：

```sql
-- 先查: SELECT COUNT(*) FROM test_case WHERE batch_id IS NULL AND is_deleted = FALSE;
-- 确认后执行:
UPDATE test_case SET is_deleted = TRUE WHERE batch_id IS NULL AND is_deleted = FALSE;
```

- [ ] **Step 11: 全量回归 + Commit**

Run: `cd backend && python -m pytest tests/ -q --deselect tests/test_storage_get_object.py`
Expected: 仅已知 storage 2 失败，其余全绿

```bash
git add -A backend/app backend/tests backend/migrations
git commit -m "feat(cases): case batch integration - generators/API/cleanup (#case-batch T2)"
```

---

### Task 3: 前端两级改造（Cases.vue 记录列表 + CaseDetail 批内用例）

**Files:**
- Modify: `frontend/src/views/Cases.vue`（改为生成记录列表）
- Modify: `frontend/src/views/CaseDetail.vue`（承接批内用例 + 评审/转脚本入口）
- Modify: `frontend/src/api/cases.js`（新增 batches API 封装；按现有 api 目录结构放置）

- [ ] **Step 1: API 封装**

在现有 cases api 文件中追加：

```javascript
// 生成记录列表
export function listCaseBatches(params) {
  return request.get('/test-cases/batches', { params })
}
// 批内用例
export function listBatchCases(batchId) {
  return request.get(`/test-cases/batches/${batchId}/cases`)
}
// 删除记录
export function deleteCaseBatch(batchId) {
  return request.delete(`/test-cases/batches/${batchId}`)
}
```

（`request` 引入方式照抄该文件现有写法。）

- [ ] **Step 2: Cases.vue 改造为记录列表**

模板结构（替换现有 el-card 内列表区，保留页头操作组的导入/导出/新建）：

```html
<el-card shadow="never">
  <div class="filter-row">
    <el-select v-model="filterProject" placeholder="项目" @change="loadBatches">
      <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
    </el-select>
    <el-select v-model="filterType" placeholder="全部类型" clearable @change="loadBatches">
      <el-option label="白盒-接口回归" value="whitescan_api" />
      <el-option label="白盒-UI回归" value="whitescan_ui" />
      <el-option label="AI需求生成" value="ai_generate" />
      <el-option label="手工创建" value="manual" />
    </el-select>
    <el-input v-model="keyword" placeholder="搜索记录名称" clearable style="width:220px" @keyup.enter="loadBatches" />
  </div>

  <el-table :data="batches" v-loading="loading" stripe>
    <el-table-column prop="batch_name" label="记录名称" min-width="280" show-overflow-tooltip />
    <el-table-column prop="batch_type" label="类型" width="140">
      <template #default="{ row }">
        <el-tag :type="typeTag(row.batch_type)">{{ typeLabel(row.batch_type) }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="case_count" label="用例数" width="90" />
    <el-table-column prop="created_at" label="创建时间" width="170">
      <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
    </el-table-column>
    <el-table-column label="操作" width="160" fixed="right">
      <template #default="{ row }">
        <el-button link type="primary" @click="viewBatch(row)">查看</el-button>
        <el-button link type="danger" @click="removeBatch(row)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
  <el-pagination layout="total, prev, pager, next" :total="total"
    :page-size="pageSize" v-model:current-page="page" @current-change="loadBatches" />
</el-card>
```

script 关键逻辑：

```javascript
const typeMap = {
  whitescan_api: { label: '白盒-接口回归', tag: 'warning' },
  whitescan_ui: { label: '白盒-UI回归', tag: 'success' },
  ai_generate: { label: 'AI需求生成', tag: 'primary' },
  manual: { label: '手工创建', tag: 'info' },
}
const typeLabel = t => typeMap[t]?.label || t
const typeTag = t => typeMap[t]?.tag || 'info'

async function loadBatches() {
  loading.value = true
  try {
    const { data } = await listCaseBatches({ project_id: filterProject.value, batch_type: filterType.value || undefined, keyword: keyword.value || undefined, page: page.value, page_size: pageSize.value })
    batches.value = data.data.items
    total.value = data.data.total
  } finally { loading.value = false }
}

function viewBatch(row) {
  router.push({ name: 'CaseDetail', query: { batch_id: row.id, batch_name: row.batch_name } })
}

async function removeBatch(row) {
  await ElMessageBox.confirm(`将删除记录《${row.batch_name}》及其 ${row.case_count} 条用例，不可恢复`, '删除确认', { type: 'warning' })
  await deleteCaseBatch(row.id)
  ElMessage.success('已删除')
  loadBatches()
}
```

删除原有平铺用例列表/批量操作逻辑（批量定稿/批量删除移到 CaseDetail）；导入导出保留在记录列表页头。

- [ ] **Step 3: CaseDetail.vue 承接批内用例 + 两个入口**

从路由 query 读 `batch_id`/`batch_name`；onMounted 拉批内用例 `listBatchCases(batch_id)` 渲染现有用例表格（沿用 CaseDetail 现有展示组件）。顶部加记录信息条：

```html
<el-alert type="info" :closable="false">
  生成记录：{{ batchName }}（共 {{ cases.length }} 条用例）
</el-alert>
```

操作区追加两个入口（勾选用例后可用）：

```html
<el-button type="primary" plain :disabled="!selected.length" @click="goReview">用例评审</el-button>
<el-button type="success" :disabled="!selected.length" @click="convertScripts">用例转自动化脚本</el-button>
```

```javascript
function goReview() {
  router.push({ name: 'ReviewCenter', query: { batch_id: batchId, case_ids: selected.value.map(c => c.id).join(',') } })
}
async function convertScripts() {
  const { data } = await convertScriptsApi({ case_ids: selected.value.map(c => c.id) })
  ElMessage.success('转换任务已提交，脚本将自动入脚本库')
}
```

（`convertScriptsApi` 即现有 `/scripts/convert` 封装，照 ScriptConvert.vue 的调用方式。ReviewCenter 需支持 query.case_ids/batch_id 预筛选——若 ReviewCenter 无此参数，本任务内加：onMounted 读 query，有 case_ids 时作为过滤条件调后端已有列表接口。）

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: build 绿（无编译错误）

- [ ] **Step 5: 手工端到端验证**

启动前后端，页面走查：记录列表加载 → 点击查看批内用例 → 勾选转脚本 → 脚本库出现脚本。

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(cases): two-level case management UI - batch list + detail entries (#case-batch T3)"
```

---

### Task 4: 转脚本命名联动 + 脚本库显示来源批次

**Files:**
- Modify: `backend/app/services/script_convert_service.py:59-68`（script_asset.name 取批次名）
- Modify: `backend/app/models/test_case.py`（ScriptAsset 加 batch_name 列，或查 test_case→case_batch 联查——采用列冗余，避免联查）
- Create: `backend/migrations/add_script_asset_batch_name.sql`
- Modify: `frontend/src/views/ScriptConvert.vue` 或脚本库列表（加"来源批次"列）

- [ ] **Step 1: 迁移 SQL**

```sql
-- script_asset 来源批次名. Idempotent.
ALTER TABLE script_asset ADD COLUMN IF NOT EXISTS batch_name VARCHAR(200);
```

- [ ] **Step 2: ScriptAsset 模型加列**

`backend/app/models/test_case.py` ScriptAsset 内：

```python
    # 所属用例生成批次名（冗余，脚本库展示来源）
    batch_name = Column(String(200))
```

- [ ] **Step 3: convert service 命名联动（先写失败测试）**

`backend/tests/test_script_convert_service.py`（已有则追加；无则新建，mock gateway/normalize 链）：

```python
def test_script_name_uses_batch_name():
    """用例属某批次 → 脚本名 = 批次名-自动化脚本HHmmss。"""
    # 构造 case dict 含 batch_name；断言 asset.name 以批次名开头且含 "自动化脚本"
```

实现：`script_convert_service.py` convert 流程取 case 后：

```python
        batch_name = case.get("batch_name")
        if batch_name:
            from datetime import datetime
            script_name = f"{batch_name}-自动化脚本{datetime.now().strftime('%H%M%S')}"
        else:
            script_name = normalized.title
        asset = ScriptAsset(
            case_id=case_id, project_id=case.get("project_id"),
            name=script_name, ...
            batch_name=batch_name,
        )
```

注意 `uq_script_asset_project_name` 唯一约束：同批多脚本时分秒可能撞名 → 同秒重名时追加 `-2`、`-3`（查同 project name 前缀计数）。测试覆盖同秒两条用例不冲突。

- [ ] **Step 4: case 载荷带 batch_name**

convert 流程读取 case 的地方（service 内 select TestCase）联查 batch_name：

```python
        from app.models.case_batch import CaseBatch
        r = await self.db.execute(
            select(TestCase, CaseBatch.batch_name)
            .outerjoin(CaseBatch, TestCase.batch_id == CaseBatch.id)
            .where(TestCase.id == case_id))
        row = r.first()
        case = row[0].to_dict() if row else None
        case["batch_name"] = row[1] if row else None
```

（以 service 现有取 case 的实际代码为准改写，保持返回结构兼容。）

- [ ] **Step 5: 前端脚本库加来源列**

脚本库表格（ScriptConvert.vue 列表区）加一列：

```html
<el-table-column prop="batch_name" label="来源批次" min-width="200" show-overflow-tooltip />
```

- [ ] **Step 6: 回归验证 + Commit**

Run: `cd backend && python -m pytest tests/test_script_convert_service.py -q && cd frontend && npm run build`
Expected: 全绿

```bash
git add backend frontend
git commit -m "feat(scripts): script naming from case batch + source column (#case-batch T4)"
```

---

## Self-Review 结论

- 命名规范（含 50 字截断/兜底）→ T1 Step 3 覆盖 ✅
- 三个生成点挂批次 → T2 Step 5/6/7 覆盖 ✅
- 历史清理（先统计后确认）→ T2 Step 10 覆盖 ✅
- 记录列表 查看/删除 → T3 Step 2 覆盖 ✅
- 查看页评审/转脚本入口 → T3 Step 3 覆盖 ✅
- 转脚本命名联动+来源列 → T4 覆盖 ✅
- 风险点已内联：路由顺序（batches 须在 /{case_id} 前）、脚本名唯一约束、ReviewCenter 预筛选参数
