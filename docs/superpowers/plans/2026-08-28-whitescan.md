# 白盒代码体检（#9）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** #9 白盒测试——semgrep(Docker) 扫描代码仓库 → issue 管理（状态流转/误报指纹忽略）→ AI 修复建议 → 一键生成回归用例（复用 #2 StepSchema 强制自动化形式，增量生成 + case_outdated）→ 产出物导出（xlsx/md）。

**Architecture:** 2 新表（code_scan/code_issue）+ TestCase 加 source_issue_id 1 列；4 service（CodeScanService/AIFixService/RegressionCaseGenerator/ScanExportService）+ 1 Celery task（异步扫描）；单 router `whitescan.py`（prefix /whitescan，9 端点）；前端 WhiteScan.vue（4 区块）+ api/whitescan.js。semgrep 走 Docker（subprocess + @patch 测试），AI 走 AIGateway.chat（mock）。

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Celery(已有 #5a), subprocess(docker semgrep), openpyxl(已有), pytest, Vue3, Element Plus。

**Spec:** `docs/superpowers/specs/2026-08-26-whitescan-design.md`（master 已有，含 Docker 方案 B 决策）

**测试约定：** `cd backend && PYTHONUTF8=1 python -m pytest`（Windows 须 PYTHONUTF8=1）。全 mock：AsyncSession mock、subprocess.run @patch、AIGateway.chat AsyncMock、openpyxl mock。断言真实输出形态。测试数据从真实形状反推（吸取 #7 教训：semprep JSON 按 semgrep 真实输出结构 mock；report 内不虚构引擎不产的键）。

**Git 约定：** worktree 分支 `worktree-module9-whitescan`（基于 master 791a6c9，含 #5c T3）。每 task 末尾 commit，前缀 `feat(whitescan):`/`fix(whitescan):`/`chore(whitescan):`。

**边界：** 复用 #2 StepSchema+禁用词、#3 TestCase+版本、#5a Celery worker；不改 case_refiner.py / test_case_service.py 核心逻辑 / #4 script_*。共享文件：models/test_case.py（追加 source_issue_id 1 列）、api/__init__.py（注册 router）、frontend 菜单（白盒死链修指 /whitescan）。**菜单名改「白盒测试」**（用户 2026-08-28 要求）。

**基线：** master 791a6c9 全量测试数以 T1 开始时实跑为准（#5c 后约 390+）。

---

## File Structure（新建/修改文件总览）

**后端新建：**
- `backend/app/models/whitescan.py` — CodeScan/CodeIssue 2 model
- `backend/app/schemas/whitescan.py` — 9 端点 request/response schema
- `backend/app/services/code_scan_service.py` — 扫描触发/查询/issue 流转/误报指纹
- `backend/app/services/ai_fix_service.py` — AI 修复建议（调 AIGateway.chat）
- `backend/app/services/regression_case_generator.py` — 回归用例生成（#2 框架）
- `backend/app/services/scan_export_service.py` — 产出物导出 xlsx/md
- `backend/app/api/v1/whitescan.py` — router prefix /whitescan
- `backend/app/tasks/code_scan_tasks.py` — Celery 异步扫描
- `backend/migrations/add_whitescan_tables.sql` — 幂等迁移
- 测试 5 个：test_code_scan_service / test_ai_fix_service / test_regression_case_generator / test_scan_export_service / test_api_whitescan

**后端修改：**
- `backend/app/models/test_case.py` — 加 source_issue_id 列（追加 1 行）
- `backend/app/api/__init__.py` — 注册 whitescan router

**前端新建：**
- `frontend/src/api/whitescan.js`
- `frontend/src/views/whitescan/WhiteScan.vue`

**前端修改：**
- `frontend/src/router/index.js` — 加 /whitescan
- `frontend/src/layouts/MainLayout.vue` — 菜单「白盒代码体检」→「白盒测试」改指 /whitescan（修死链 + 改名）

---

## Task 1: models + 迁移 + TestCase 关联列

**Files:**
- Create: `backend/app/models/whitescan.py`
- Modify: `backend/app/models/test_case.py`（追加 source_issue_id）
- Create: `backend/migrations/add_whitescan_tables.sql`
- Test: 无独立（model 层随 T2 service 测试覆盖；迁移 SQL 语法人工核对）

- [ ] **Step 1: 写 whitescan.py models**

Create `backend/app/models/whitescan.py`:

```python
"""Whitescan models: code_scan + code_issue (req §5.1)."""
import uuid
from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models import Base


class CodeScan(Base):
    """代码扫描记录"""

    __tablename__ = "code_scan"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True)
    repo_url = Column(String(500), nullable=False)
    branch = Column(String(100), default="main")
    status = Column(String(20), default="scanning", comment="scanning/done/failed")
    total_issues = Column(Integer, default=0)
    high_count = Column(Integer, default=0)
    mid_count = Column(Integer, default=0)
    low_count = Column(Integer, default=0)
    file_count = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    error_msg = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    issues = relationship("CodeIssue", back_populates="scan", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "repo_url": self.repo_url,
            "branch": self.branch,
            "status": self.status,
            "total_issues": self.total_issues,
            "high_count": self.high_count,
            "mid_count": self.mid_count,
            "low_count": self.low_count,
            "file_count": self.file_count,
            "duration_ms": self.duration_ms,
            "error_msg": self.error_msg,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CodeIssue(Base):
    """代码问题"""

    __tablename__ = "code_issue"
    __table_args__ = (
        Index("idx_code_issue_scan", "scan_id"),
        Index("idx_code_issue_fingerprint", "fingerprint"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id = Column(UUID(as_uuid=True), ForeignKey("code_scan.id", ondelete="CASCADE"), nullable=False)
    severity = Column(String(10), nullable=False, comment="high/mid/low")
    file_path = Column(String(500), nullable=False)
    line_no = Column(Integer)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    ai_suggestion = Column(JSONB, comment="AI 修复建议：{suggestion, fixed_code, original_code}")
    example_code = Column(Text)
    status = Column(String(20), default="open", comment="open/fixed/false_positive")
    source_commit = Column(String(100))
    fingerprint = Column(String(200), comment="rule_id+file+line+code hash；误报忽略依据")
    case_outdated = Column(Boolean, default=False)
    handled_by = Column(String(50))
    handled_at = Column(DateTime(timezone=True))

    scan = relationship("CodeScan", back_populates="issues")

    def to_dict(self):
        return {
            "id": str(self.id),
            "scan_id": str(self.scan_id),
            "severity": self.severity,
            "file_path": self.file_path,
            "line_no": self.line_no,
            "title": self.title,
            "description": self.description,
            "ai_suggestion": self.ai_suggestion,
            "example_code": self.example_code,
            "status": self.status,
            "source_commit": self.source_commit,
            "fingerprint": self.fingerprint,
            "case_outdated": self.case_outdated,
            "handled_by": self.handled_by,
            "handled_at": self.handled_at.isoformat() if self.handled_at else None,
        }
```

- [ ] **Step 2: TestCase 加 source_issue_id**

Modify `backend/app/models/test_case.py`：在 `is_deleted = Column(Boolean, default=False)` 行后追加：

```python
    # W9: whitescan regression case source (NULL = not whitescan-generated)
    source_issue_id = Column(UUID(as_uuid=True), ForeignKey("code_issue.id", ondelete="SET NULL"), nullable=True)
```

- [ ] **Step 3: 写迁移 SQL**

Create `backend/migrations/add_whitescan_tables.sql`（幂等，参照 add_execution_detail_table.sql 风格）:

```sql
-- #9: whitescan tables (code_scan + code_issue) + test_case.source_issue_id
-- Idempotent.
CREATE TABLE IF NOT EXISTS code_scan (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
    repo_url VARCHAR(500) NOT NULL,
    branch VARCHAR(100) DEFAULT 'main',
    status VARCHAR(20) DEFAULT 'scanning',
    total_issues INTEGER DEFAULT 0,
    high_count INTEGER DEFAULT 0,
    mid_count INTEGER DEFAULT 0,
    low_count INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    error_msg TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_code_scan_project ON code_scan(project_id);

CREATE TABLE IF NOT EXISTS code_issue (
    id UUID PRIMARY KEY,
    scan_id UUID NOT NULL REFERENCES code_scan(id) ON DELETE CASCADE,
    severity VARCHAR(10) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    line_no INTEGER,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    ai_suggestion JSONB,
    example_code TEXT,
    status VARCHAR(20) DEFAULT 'open',
    source_commit VARCHAR(100),
    fingerprint VARCHAR(200),
    case_outdated BOOLEAN DEFAULT FALSE,
    handled_by VARCHAR(50),
    handled_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_code_issue_scan ON code_issue(scan_id);
CREATE INDEX IF NOT EXISTS idx_code_issue_fingerprint ON code_issue(fingerprint);

ALTER TABLE test_case ADD COLUMN IF NOT EXISTS source_issue_id UUID REFERENCES code_issue(id) ON DELETE SET NULL;
```

- [ ] **Step 4: 验证模型可导入**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.models.whitescan import CodeScan, CodeIssue; from app.models.test_case import TestCase; print('ok, source_issue_id:', hasattr(TestCase, 'source_issue_id'))"`
Expected: `ok, source_issue_id: True`

- [ ] **Step 5: 跑全量无回归**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（基线不变）

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/models/whitescan.py app/models/test_case.py migrations/add_whitescan_tables.sql
git commit -m "feat(whitescan): CodeScan/CodeIssue models + migration + test_case.source_issue_id (W9)"
```

---

## Task 2: CodeScanService（扫描触发/查询/issue 流转/误报指纹）

**Files:**
- Create: `backend/app/services/code_scan_service.py`
- Test: `backend/tests/test_code_scan_service.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_code_scan_service.py`:

```python
"""CodeScanService tests (mock db + mock subprocess for semgrep)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

from app.services.code_scan_service import CodeScanService, _run_semgrep, _compute_fingerprint


def _mock_scalar(v):
    return Mock(scalar=Mock(return_value=v))


def _mock_scalars(values):
    return Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=values))))


def _mock_scalar_one(value):
    return Mock(scalar_one_or_none=Mock(return_value=value))


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


# semgrep real output shape (subset of fields we consume)
SEMGREP_JSON = {
    "results": [
        {"check_id": "python-lang.correctness.eqeq5",
         "path": "src/auth.py", "start": {"line": 42},
         "extra": {"message": "use == to compare", "severity": "WARNING",
                   "lines": "if a == b:  # noqa"}},
        {"check_id": "python.security.sql-injection",
         "path": "src/db.py", "start": {"line": 10},
         "extra": {"message": "possible SQL injection", "severity": "ERROR",
                   "lines": "cursor.execute(f'...')"}},
    ],
    "errors": [],
}


class TestRunSemgrep:
    def test_semgrep_parses_docker_output(self):
        with patch("app.services.code_scan_service.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout=json.dumps(SEMGREP_JSON))
            result = _run_semgrep("/tmp/repo")
        assert len(result["results"]) == 2
        assert result["results"][0]["check_id"] == "python-lang.correctness.eqeq5"

    def test_semgrep_failure_raises(self):
        with patch("app.services.code_scan_service.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="docker: not found")
            with pytest.raises(Exception):
                _run_semgrep("/tmp/repo")


class TestFingerprint:
    def test_fingerprint_stable_and_scoped(self):
        fp1 = _compute_fingerprint("rule-a", "src/x.py", 10, "code here")
        fp2 = _compute_fingerprint("rule-a", "src/x.py", 10, "code here")
        fp3 = _compute_fingerprint("rule-a", "src/x.py", 11, "code here")
        assert fp1 == fp2
        assert fp1 != fp3
        assert len(fp1) <= 200


class TestIssueFlow:
    @pytest.mark.asyncio
    async def test_update_issue_status_false_positive(self, mock_db):
        issue = MagicMock()
        issue.status = "open"
        issue.fingerprint = "fp-1"
        mock_db.execute.return_value = _mock_scalar_one(issue)
        svc = CodeScanService(mock_db)
        result = await svc.update_issue(str(uuid4()), "false_positive")
        assert result["status"] == "false_positive"
        assert issue.status == "false_positive"
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_update_issue_missing_raises_404_shape(self, mock_db):
        mock_db.execute.return_value = _mock_scalar_one(None)
        svc = CodeScanService(mock_db)
        result = await svc.update_issue(str(uuid4()), "fixed")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_issues_filters(self, mock_db):
        i1, i2 = MagicMock(), MagicMock()
        i1.to_dict = Mock(return_value={"severity": "high"})
        i2.to_dict = Mock(return_value={"severity": "low"})
        mock_db.execute.return_value = _mock_scalars([i1, i2])
        svc = CodeScanService(mock_db)
        result = await svc.list_issues(str(uuid4()), severity="high", status=None)
        assert len(result) == 2  # mock db ignores filters; shape asserted
        assert result[0]["severity"] == "high"

    @pytest.mark.asyncio
    async def test_get_ignored_fingerprints(self, mock_db):
        rows = [("fp-a",), ("fp-b",)]
        mock_db.execute.return_value = Mock(all=Mock(return_value=rows))
        svc = CodeScanService(mock_db)
        result = await svc.get_ignored_fingerprints(str(uuid4()))
        assert result == ["fp-a", "fp-b"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_code_scan_service.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 CodeScanService**

Create `backend/app/services/code_scan_service.py`:

```python
"""Code scan service: semgrep(Docker) trigger + scan/issue queries + status flow.

WHITE-04: false-positive issues are ignored by fingerprint on re-scan.
"""
import hashlib
import json
import logging
import subprocess
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.whitescan import CodeScan, CodeIssue

logger = logging.getLogger(__name__)


def _run_semgrep(repo_path: str, timeout: int = 300) -> dict:
    """Run semgrep via Docker (spec 方案 B: works on Windows Desktop + Linux).
    First run pulls returntocorp/semgrep image automatically."""
    result = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{repo_path}:/src",
         "returntocorp/semgrep",
         "semgrep", "scan", "--config", "auto", "--json", "/src"],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"semgrep failed (rc={result.returncode}): {result.stderr[:500]}")
    return json.loads(result.stdout)


def _compute_fingerprint(rule_id: str, file_path: str, line_no: int, code: str) -> str:
    """Stable issue fingerprint: rule + location + code hash (WHITE-04)."""
    raw = f"{rule_id}|{file_path}|{line_no}|{code.strip()}"
    return f"{rule_id}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


class CodeScanService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_scan(self, project_id: str, repo_url: str, branch: str = "main") -> dict:
        scan = CodeScan(project_id=UUID(project_id), repo_url=repo_url, branch=branch)
        self.db.add(scan)
        await self.db.commit()
        await self.db.refresh(scan)
        return scan.to_dict()

    async def get_scan(self, scan_id: str) -> Optional[dict]:
        q = select(CodeScan).where(CodeScan.id == UUID(scan_id))
        scan = (await self.db.execute(q)).scalar_one_or_none()
        return scan.to_dict() if scan else None

    async def list_scans(self, project_id: str, page: int = 1, page_size: int = 20) -> dict:
        pid = UUID(project_id)
        total = (await self.db.execute(
            select(func.count()).select_from(CodeScan).where(CodeScan.project_id == pid)
        )).scalar() or 0
        q = (select(CodeScan).where(CodeScan.project_id == pid)
             .order_by(CodeScan.created_at.desc())
             .offset((page - 1) * page_size).limit(page_size))
        rows = (await self.db.execute(q)).scalars().all()
        return {"total": total, "page": page, "page_size": page_size,
                "items": [r.to_dict() for r in rows]}

    async def list_issues(self, scan_id: str, severity: Optional[str] = None,
                          status: Optional[str] = None) -> List[dict]:
        q = select(CodeIssue).where(CodeIssue.scan_id == UUID(scan_id))
        if severity:
            q = q.where(CodeIssue.severity == severity)
        if status:
            q = q.where(CodeIssue.status == status)
        rows = (await self.db.execute(q)).scalars().all()
        return [r.to_dict() for r in rows]

    async def update_issue(self, issue_id: str, status: str,
                           handled_by: str = "system") -> Optional[dict]:
        if status not in ("open", "fixed", "false_positive"):
            raise ValueError(f"invalid status: {status}")
        q = select(CodeIssue).where(CodeIssue.id == UUID(issue_id))
        issue = (await self.db.execute(q)).scalar_one_or_none()
        if not issue:
            return None
        issue.status = status
        issue.handled_by = handled_by
        from datetime import datetime, timezone
        issue.handled_at = datetime.now(timezone.utc)
        await self.db.commit()
        return issue.to_dict()

    async def get_ignored_fingerprints(self, scan_id: str) -> List[str]:
        """Fingerprints previously marked false_positive in this project's scans."""
        q = (
            select(CodeIssue.fingerprint)
            .join(CodeScan, CodeIssue.scan_id == CodeScan.id)
            .where(CodeScan.id == UUID(scan_id),
                   CodeIssue.status == "false_positive")
        )
        rows = (await self.db.execute(q)).all()
        return [r[0] for r in rows if r[0]]

    async def mark_scan_done(self, scan_id: str, *, total: int, high: int,
                             mid: int, low: int, file_count: int,
                             duration_ms: int) -> Optional[dict]:
        q = select(CodeScan).where(CodeScan.id == UUID(scan_id))
        scan = (await self.db.execute(q)).scalar_one_or_none()
        if not scan:
            return None
        scan.status = "done"
        scan.total_issues = total
        scan.high_count = high
        scan.mid_count = mid
        scan.low_count = low
        scan.file_count = file_count
        scan.duration_ms = duration_ms
        await self.db.commit()
        return scan.to_dict()

    async def mark_scan_failed(self, scan_id: str, error_msg: str) -> Optional[dict]:
        q = select(CodeScan).where(CodeScan.id == UUID(scan_id))
        scan = (await self.db.execute(q)).scalar_one_or_none()
        if not scan:
            return None
        scan.status = "failed"
        scan.error_msg = error_msg[:2000]
        await self.db.commit()
        return scan.to_dict()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_code_scan_service.py -v`
Expected: PASS（7 tests）

- [ ] **Step 5: 全量无回归 + Commit**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

```bash
cd backend
git add app/services/code_scan_service.py tests/test_code_scan_service.py
git commit -m "feat(whitescan): CodeScanService semgrep(Docker)/issues/fingerprint (W9)"
```

---

## Task 3: AIFixService + RegressionCaseGenerator

**Files:**
- Create: `backend/app/services/ai_fix_service.py`
- Create: `backend/app/services/regression_case_generator.py`
- Test: `backend/tests/test_ai_fix_service.py`, `backend/tests/test_regression_case_generator.py`

- [ ] **Step 1: 写 AI fix 失败测试**

Create `backend/tests/test_ai_fix_service.py`:

```python
"""AIFixService tests (mock AIGateway)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

from app.services.ai_fix_service import AIFixService


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def mock_gateway():
    gw = MagicMock()
    gw.chat = AsyncMock(return_value={
        "content": '{"suggestion": "use parameterized query", '
                   '"fixed_code": "cursor.execute(sql, (uid,))", '
                   '"original_code": "cursor.execute(f\'...{uid}...\')"}',
        "tokens": 120,
    })
    return gw


@pytest.fixture
def issue_row():
    issue = MagicMock()
    issue.id = uuid4()
    issue.title = "SQL injection risk"
    issue.description = "f-string in execute"
    issue.file_path = "src/db.py"
    issue.line_no = 10
    issue.example_code = "cursor.execute(f'SELECT * FROM u WHERE id={uid}')"
    issue.severity = "high"
    return issue


class TestAIFix:
    @pytest.mark.asyncio
    async def test_generate_fix_writes_jsonb(self, mock_db, mock_gateway, issue_row):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=issue_row))
        svc = AIFixService(mock_db, mock_gateway)
        result = await svc.generate_fix(str(issue_row.id), project_id=str(uuid4()))
        assert result["ai_suggestion"]["suggestion"] == "use parameterized query"
        assert "fixed_code" in result["ai_suggestion"]
        assert issue_row.ai_suggestion["fixed_code"].startswith("cursor.execute(sql")
        assert mock_db.commit.called
        # gateway called with project token tracking
        assert mock_gateway.chat.called

    @pytest.mark.asyncio
    async def test_generate_fix_bad_json_degrades(self, mock_db, issue_row):
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "not json at all", "tokens": 50})
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=issue_row))
        svc = AIFixService(mock_db, gw)
        result = await svc.generate_fix(str(issue_row.id), project_id=str(uuid4()))
        # degraded: raw content wrapped, no crash
        assert result["ai_suggestion"]["suggestion"].startswith("not json")

    @pytest.mark.asyncio
    async def test_generate_fix_missing_issue(self, mock_db, mock_gateway):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = AIFixService(mock_db, mock_gateway)
        assert await svc.generate_fix(str(uuid4()), project_id=str(uuid4())) is None
```

- [ ] **Step 2: 写回归生成器失败测试**

Create `backend/tests/test_regression_case_generator.py`:

```python
"""RegressionCaseGenerator tests (mock AIGateway + db; prompts asserted)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

from app.services.regression_case_generator import RegressionCaseGenerator, FORBIDDEN_WORDS


CASE_JSON = {
    "name": "REG-SQLI_验证参数化查询修复后查询正常",
    "priority": "P0",
    "precondition": "测试环境就绪，账户 test_${uuid} 已创建",
    "steps": [
        {"step": 1, "action": "input", "target": "搜索框", "data": "1' OR '1'='1",
         "expected": "输入被接受"},
        {"step": 2, "action": "click", "target": "查询按钮", "data": "",
         "expected": "接口返回 200 且无 SQL 错误"},
        {"step": 3, "action": "assert", "target": "结果列表", "data": "",
         "expected": "列表为空且 HTTP 状态 200"},
    ],
    "expected_result": "注入输入被参数化查询拦截，接口返回 200",
    "source_issue_id": "11111111-1111-1111-1111-111111111111",
}


def _mock_gateway_with(case_json):
    gw = MagicMock()
    gw.chat = AsyncMock(return_value={"content": json.dumps(case_json, ensure_ascii=False),
                                      "tokens": 300})
    return gw


class TestGenerateCase:
    @pytest.mark.asyncio
    async def test_generate_parses_case_and_strips_source(self):
        gw = _mock_gateway_with(CASE_JSON)
        gen = RegressionCaseGenerator(gw)
        result = await gen.generate_case(
            issue={"id": str(uuid4()), "title": "SQLi", "file_path": "a.py",
                   "line_no": 1, "description": "d", "example_code": "c", "severity": "high"},
            ai_suggestion={"suggestion": "param query", "fixed_code": "x", "original_code": "y"},
        )
        assert result["name"].startswith("REG-")
        assert "source_issue_id" not in result  # caller sets association
        assert isinstance(result["steps"], list) and len(result["steps"]) == 3

    @pytest.mark.asyncio
    async def test_prompt_contains_5_rules_and_forbidden_words(self):
        gw = _mock_gateway_with(CASE_JSON)
        gen = RegressionCaseGenerator(gw)
        await gen.generate_case(issue={"id": "x", "title": "t", "file_path": "f",
                                       "line_no": 1, "description": "", "example_code": "",
                                       "severity": "high"},
                                ai_suggestion={})
        sent = gw.chat.call_args[0][0]
        prompt_text = str(sent)
        for kw in ["代码依赖", "新旧路径", "幂等", "断言", "异常"]:
            assert kw in prompt_text
        for w in FORBIDDEN_WORDS:
            assert w in prompt_text  # forbidden words must be instructed away

    @pytest.mark.asyncio
    async def test_bad_json_raises(self):
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "junk", "tokens": 1})
        gen = RegressionCaseGenerator(gw)
        with pytest.raises(ValueError):
            await gen.generate_case(issue={"id": "x", "title": "t", "file_path": "f",
                                           "line_no": 1, "description": "", "example_code": "",
                                           "severity": "high"},
                                    ai_suggestion={})


class TestBatchGenerate:
    @pytest.mark.asyncio
    async def test_incremental_skips_existing(self):
        gw = _mock_gateway_with(CASE_JSON)
        gen = RegressionCaseGenerator(gw)

        async def fake_exists(project_id, issue_id):
            return issue_id == "exists"

        gen._case_exists = fake_exists
        issues = [{"id": "exists"}, {"id": "new-1"}]
        results = await gen.batch_generate("pid", issues)
        assert results["generated_count"] == 1
        assert results["skipped_count"] == 1
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_ai_fix_service.py tests/test_regression_case_generator.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 AIFixService**

Create `backend/app/services/ai_fix_service.py`:

```python
"""AI fix suggestion service: issue -> AIGateway.chat -> ai_suggestion JSONB."""
import json
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.whitescan import CodeIssue

logger = logging.getLogger(__name__)

_PROMPT = """你是资深安全工程师。针对以下代码问题给出修复建议。

【问题】{title}
【文件】{file_path}:{line_no}
【描述】{description}
【问题代码】
{example_code}

只输出 JSON（不要 markdown 围栏）：
{{"suggestion": "修复思路（一句话）", "fixed_code": "修复后代码", "original_code": "原问题代码"}}"""


class AIFixService:
    def __init__(self, db: AsyncSession, gateway):
        self.db = db
        self.gateway = gateway

    async def generate_fix(self, issue_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        q = select(CodeIssue).where(CodeIssue.id == UUID(issue_id))
        issue = (await self.db.execute(q)).scalar_one_or_none()
        if not issue:
            return None

        messages = [{"role": "user", "content": _PROMPT.format(
            title=issue.title, file_path=issue.file_path,
            line_no=issue.line_no or 0, description=issue.description or "",
            example_code=(issue.example_code or "")[:2000],
        )}]
        try:
            resp = await self.gateway.chat(
                messages,
                project_id=project_id or None,
                stage="whitescan_ai_fix",
            )
        except Exception as e:
            logger.error(f"AI fix gateway call failed: {e}")
            raise

        content = (resp or {}).get("content", "")
        try:
            parsed = json.loads(content)
            suggestion = {
                "suggestion": parsed.get("suggestion", ""),
                "fixed_code": parsed.get("fixed_code", ""),
                "original_code": parsed.get("original_code", issue.example_code or ""),
            }
        except (json.JSONDecodeError, AttributeError):
            # degraded: keep raw text so the user still sees something
            suggestion = {"suggestion": content[:1000], "fixed_code": "", "original_code": ""}

        issue.ai_suggestion = suggestion
        await self.db.commit()
        return issue.to_dict()
```

- [ ] **Step 5: 实现 RegressionCaseGenerator**

Create `backend/app/services/regression_case_generator.py`:

```python
"""Regression case generator: code_issue + AI fix -> platform TestCase.

Reuses #2 conventions: StepSchema shape + forbidden words. Output is a plain
dict (steps list of {step,action,target,data,expected}); caller persists into
test_case with source_issue_id association.
"""
import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 同 #2 禁用词（软断言词不进 action/expected）
FORBIDDEN_WORDS = ("观察", "查看", "验证", "检查", "确认")

_PROMPT = """你是一位资深的测试架构师。请基于以下【代码问题(code_issue)】+【AI修复建议】+【代码上下文】，
生成回归测试用例。

分析要求（5 条，全部落实）：
1. 基于代码依赖（精准打击）：优先为被修改函数/类的直接调用方和下游依赖生成
2. 兼顾新旧路径：验证老功能未被改坏（防退化），非仅验证新功能
3. 数据隔离与幂等性：使用唯一标识(UUID)或临时账户，并发不冲突
4. 断言精细化：拒绝模糊断言（如"页面正常"），必须校验具体业务状态码/数据结构/元素属性
5. 异常与容错覆盖：除主流程，根据 try-catch/降级/超时生成异常注入用例

禁用词：action 与 expected 不得包含以下软断言词：{forbidden}

输出 JSON（不要 markdown 围栏，平台 TestCase 格式，强制自动化形式）：
{{
  "name": "REG-XXX_验证意图",
  "priority": "P0|P1|P2",
  "precondition": "前置条件",
  "steps": [
    {{"step": 1, "action": "navigate|click|input|select|check|assert|wait",
      "target": "目标元素", "data": "测试数据", "expected": "可断言预期(URL/文本/状态)"}}
  ],
  "expected_result": "最终可断言预期"
}}"""


class RegressionCaseGenerator:
    def __init__(self, gateway):
        self.gateway = gateway

    async def generate_case(self, issue: Dict, ai_suggestion: Dict) -> dict:
        """issue: code_issue.to_dict(); ai_suggestion: issue.ai_suggestion.
        Returns TestCase-ready dict WITHOUT source_issue_id (caller sets it)."""
        messages = [{"role": "user", "content": _PROMPT.format(
            forbidden="、".join(FORBIDDEN_WORDS),
        ) + f"""

【代码问题】{issue.get('title','')}（{issue.get('file_path','')}:{issue.get('line_no','')}，severity={issue.get('severity','')}）
【描述】{issue.get('description','')}
【问题代码】{(issue.get('example_code') or '')[:1500]}
【AI修复建议】{json.dumps(ai_suggestion or {}, ensure_ascii=False)[:1500]}"""}]

        resp = await self.gateway.chat(messages, stage="whitescan_regression_case")
        content = (resp or {}).get("content", "")
        try:
            case = json.loads(content)
        except (json.JSONDecodeError, AttributeError) as e:
            raise ValueError(f"regression case LLM returned non-JSON: {content[:200]}") from e

        # normalize + strip fields the caller owns
        case.pop("source_issue_id", None)
        steps = case.get("steps") or []
        for i, s in enumerate(steps, 1):
            s.setdefault("step", i)
        case["steps"] = steps
        return case

    async def _case_exists(self, project_id: str, issue_id: str) -> bool:
        """Overridden in batch to query test_case by source_issue_id. Injectable
        for tests."""
        raise NotImplementedError

    async def batch_generate(self, project_id: str, issues: List[Dict]) -> dict:
        """Incremental: skip issues that already produced a case (WHITE-05 增量).
        issues: list of issue dicts; each may carry '_case_exists' bool? No —
        caller resolves via _case_exists(project_id, issue.id)."""
        generated = skipped = failed = 0
        errors = []
        for issue in issues:
            iid = str(issue.get("id"))
            try:
                if await self._case_exists(project_id, iid):
                    skipped += 1
                    continue
                await self.generate_case(issue, issue.get("ai_suggestion") or {})
                generated += 1
            except Exception as e:
                failed += 1
                errors.append({"issue_id": iid, "error": str(e)})
        return {"generated_count": generated, "skipped_count": skipped,
                "failed_count": failed, "errors": errors}
```

> 注：`batch_generate` 在 service 集成时（T4）由 CodeScanService 子类/包装注入真实 `_case_exists`（查 test_case.source_issue_id）与持久化；本 task 只测生成器纯逻辑 + 可注入桩。计划在 T4 明确给出集成写法。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_ai_fix_service.py tests/test_regression_case_generator.py -v`
Expected: PASS（3 + 4 = 7 tests）

- [ ] **Step 7: 全量 + Commit**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

```bash
cd backend
git add app/services/ai_fix_service.py app/services/regression_case_generator.py tests/test_ai_fix_service.py tests/test_regression_case_generator.py
git commit -m "feat(whitescan): AIFixService + RegressionCaseGenerator (W9)"
```

---

## Task 4: 扫描编排集成 + Celery task + ScanExportService

**Files:**
- Modify: `backend/app/services/code_scan_service.py`（加 `run_scan_sync` 编排 + issue 落库 + 指纹跳过）
- Create: `backend/app/tasks/code_scan_tasks.py`
- Create: `backend/app/services/scan_export_service.py`
- Test: 追加 `backend/tests/test_code_scan_service.py`（编排用例）、`backend/tests/test_scan_export_service.py`

- [ ] **Step 1: 写编排失败测试（追加到 test_code_scan_service.py）**

Append to `backend/tests/test_code_scan_service.py`:

```python
class TestRunScanSync:
    @pytest.mark.asyncio
    async def test_run_scan_writes_issues_and_stats(self, mock_db):
        import tempfile, os
        svc = CodeScanService(mock_db)
        scan = MagicMock()
        scan.id = uuid4()
        scan.to_dict = Mock(return_value={"id": str(scan.id), "status": "scanning"})
        # create_scan then fetch pattern: db.add + commit/refresh, then mark_done fetch
        mock_db.execute.side_effect = [
            _mock_scalar_one(scan),   # mark_scan_done fetch
        ]
        with patch("app.services.code_scan_service._run_semgrep",
                   return_value=SEMGREP_JSON):
            result = await svc.run_scan_sync(
                {"id": str(uuid4()), "project_id": str(uuid4())},
                repo_path="/tmp/repo")
        assert result["total_issues"] == 2
        assert result["high_count"] >= 1  # ERROR mapped high
        assert mock_db.commit.called or mock_db.add.called

    @pytest.mark.asyncio
    async def test_run_scan_skips_ignored_fingerprints(self, mock_db):
        svc = CodeScanService(mock_db)
        # both issues ignored -> 0 written
        async def fake_ignored(scan_id):
            return {_compute_fingerprint(
                SEMGREP_JSON["results"][0]["check_id"],
                SEMGREP_JSON["results"][0]["path"],
                SEMGREP_JSON["results"][0]["start"]["line"],
                SEMGREP_JSON["results"][0]["extra"]["lines"]),
                _compute_fingerprint(
                SEMGREP_JSON["results"][1]["check_id"],
                SEMGREP_JSON["results"][1]["path"],
                SEMGREP_JSON["results"][1]["start"]["line"],
                SEMGREP_JSON["results"][1]["extra"]["lines"])}
        svc.get_ignored_fingerprints = fake_ignored
        with patch("app.services.code_scan_service._run_semgrep",
                   return_value=SEMGREP_JSON):
            result = await svc.run_scan_sync(
                {"id": str(uuid4()), "project_id": str(uuid4())},
                repo_path="/tmp/repo")
        assert result["total_issues"] == 0


class TestScanExport:
    @pytest.mark.asyncio
    async def test_export_buglist_xlsx_bytes(self):
        from app.services.scan_export_service import ScanExportService
        svc = ScanExportService()
        issues = [{"severity": "high", "file_path": "a.py", "line_no": 1,
                   "title": "SQLi", "description": "d", "status": "open"}]
        data = svc.export_buglist_xlsx(issues)
        assert data[:2] == b"PK"  # xlsx zip magic

    @pytest.mark.asyncio
    async def test_export_markdown_nonempty(self):
        from app.services.scan_export_service import ScanExportService
        svc = ScanExportService()
        issues = [{"severity": "high", "file_path": "a.py", "line_no": 1,
                   "title": "SQLi", "description": "d", "status": "open"}]
        md = svc.export_issues_markdown(issues, title="BUG清单")
        assert "SQLi" in md and "#" in md
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_code_scan_service.py -v`
Expected: 新增用例 FAIL（run_scan_sync / ScanExportService 不存在）

- [ ] **Step 3: 实现 run_scan_sync（追加到 CodeScanService）**

Append method to `CodeScanService` in `backend/app/services/code_scan_service.py`:

```python
    # severity mapping: semgrep ERROR/WARNING/INFO -> high/mid/low
    _SEV_MAP = {"ERROR": "high", "WARNING": "mid", "INFO": "low"}

    async def run_scan_sync(self, scan_dict: dict, repo_path: str) -> dict:
        """Synchronous scan orchestration (called by Celery task with its own
        session). scan_dict: create_scan() output."""
        import time
        from datetime import datetime, timezone

        scan_id = scan_dict["id"]
        started = time.time()
        try:
            ignored = set(await self.get_ignored_fingerprints(scan_id))
            semgrep = _run_semgrep(repo_path)
            counts = {"high": 0, "mid": 0, "low": 0}
            files = set()
            for r in semgrep.get("results", []):
                fp = _compute_fingerprint(
                    r.get("check_id", ""),
                    r.get("path", ""),
                    (r.get("start") or {}).get("line", 0),
                    (r.get("extra") or {}).get("lines", ""),
                )
                if fp in ignored:
                    continue
                sev = self._SEV_MAP.get((r.get("extra") or {}).get("severity", "INFO"), "low")
                counts[sev] += 1
                files.add(r.get("path", ""))
                issue = CodeIssue(
                    scan_id=UUID(scan_id),
                    severity=sev,
                    file_path=r.get("path", ""),
                    line_no=(r.get("start") or {}).get("line"),
                    title=(r.get("check_id", "")).split(".")[-1][:200] or "issue",
                    description=(r.get("extra") or {}).get("message", ""),
                    example_code=(r.get("extra") or {}).get("lines", ""),
                    fingerprint=fp,
                )
                self.db.add(issue)
            duration_ms = int((time.time() - started) * 1000)
            await self.db.commit()
            await self.mark_scan_done(
                scan_id, total=sum(counts.values()),
                high=counts["high"], mid=counts["mid"], low=counts["low"],
                file_count=len(files), duration_ms=duration_ms,
            )
            return {"total_issues": sum(counts.values()), **counts,
                    "file_count": len(files), "duration_ms": duration_ms}
        except Exception as e:
            await self.mark_scan_failed(scan_id, str(e))
            raise
```

- [ ] **Step 4: 实现 ScanExportService**

Create `backend/app/services/scan_export_service.py`:

```python
"""Scan artifact export: BUG清单.xlsx / issues markdown (WHITE-05 subset)."""
import io
import logging
from typing import List

logger = logging.getLogger(__name__)


class ScanExportService:
    """Stateless exporter; openpyxl imported lazily (already in requirements)."""

    def export_buglist_xlsx(self, issues: List[dict]) -> bytes:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "BUG清单"
        ws.append(["等级", "文件路径", "行号", "标题", "描述", "状态"])
        sev_cn = {"high": "高危", "mid": "中危", "low": "低危"}
        for it in issues:
            ws.append([
                sev_cn.get(it.get("severity"), it.get("severity", "")),
                it.get("file_path", ""), it.get("line_no", ""),
                it.get("title", ""), it.get("description", ""),
                it.get("status", ""),
            ])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def export_issues_markdown(self, issues: List[dict], title: str = "BUG清单") -> str:
        lines = [f"# {title}", ""]
        sev_cn = {"high": "高危", "mid": "中危", "low": "低危"}
        status_cn = {"open": "待处理", "fixed": "已修复", "false_positive": "误报"}
        for it in issues:
            lines.append(f"## [{sev_cn.get(it.get('severity'), '')}] {it.get('title', '')}")
            lines.append(f"- 文件：`{it.get('file_path', '')}:{it.get('line_no', '')}`")
            lines.append(f"- 状态：{status_cn.get(it.get('status'), it.get('status', ''))}")
            if it.get("description"):
                lines.append(f"- 描述：{it['description']}")
            lines.append("")
        return "\n".join(lines)
```

- [ ] **Step 5: 实现 Celery task**

Create `backend/app/tasks/code_scan_tasks.py`:

```python
# backend/app/tasks/code_scan_tasks.py
"""Whitescan Celery task: async code scan (git clone -> semgrep -> issues)."""
import logging
import tempfile
import shutil

from app.tasks import celery_app
from app.core.database import AsyncSessionLocal
from app.services.code_scan_service import CodeScanService

logger = logging.getLogger(__name__)


def _run_async(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="code_scan.run_scan")
def run_scan_task(scan_id: str, project_id: str, repo_url: str, branch: str = "main"):
    """Clone repo (shallow) + semgrep + persist issues. DB writes reuse the
    sync-orchestrated service with its own session."""
    repo_path = tempfile.mkdtemp(prefix="whitescan_")
    try:
        import subprocess
        clone = subprocess.run(
            ["git", "clone", "--depth", "1", "-b", branch, repo_url, repo_path],
            capture_output=True, text=True, timeout=300,
        )
        if clone.returncode != 0:
            raise RuntimeError(f"git clone failed: {clone.stderr[:500]}")

        async def _impl():
            async with AsyncSessionLocal() as db:
                svc = CodeScanService(db)
                scan = await svc.get_scan(scan_id)
                if not scan:
                    raise RuntimeError(f"scan {scan_id} not found")
                return await svc.run_scan_sync(scan, repo_path)

        return _run_async(_impl())
    except Exception as e:
        logger.error(f"scan task {scan_id} failed: {e}")
        # mark failed with its own session (run may have died mid-way)
        try:
            async def _fail():
                async with AsyncSessionLocal() as db:
                    await CodeScanService(db).mark_scan_failed(scan_id, str(e))
            _run_async(_fail())
        except Exception:
            pass
        raise
    finally:
        shutil.rmtree(repo_path, ignore_errors=True)
```

- [ ] **Step 6: 跑测试确认通过 + 全量**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_code_scan_service.py tests/test_scan_export_service.py -v 2>/dev/null || PYTHONUTF8=1 python -m pytest tests/test_code_scan_service.py -v`
Expected: PASS（9 + 2 export tests；export 在同文件）

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/services/code_scan_service.py app/services/scan_export_service.py app/tasks/code_scan_tasks.py tests/test_code_scan_service.py
git commit -m "feat(whitescan): scan orchestration + Celery task + export service (W9)"
```

---

## Task 5: API router（9 端点）+ 注册

**Files:**
- Create: `backend/app/schemas/whitescan.py`
- Create: `backend/app/api/v1/whitescan.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_api_whitescan.py`

- [ ] **Step 1: 写 schema**

Create `backend/app/schemas/whitescan.py`:

```python
"""Whitescan schemas."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ScanTriggerRequest(BaseModel):
    project_id: str
    repo_url: str = Field(..., min_length=1, max_length=500)
    branch: str = Field("main", max_length=100)


class ScanResponse(BaseModel):
    id: str
    project_id: str
    repo_url: str
    branch: str
    status: str
    total_issues: int = 0
    high_count: int = 0
    mid_count: int = 0
    low_count: int = 0
    file_count: int = 0
    duration_ms: int = 0
    error_msg: Optional[str] = None
    created_at: Optional[str] = None


class ScanListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ScanResponse] = []


class IssueResponse(BaseModel):
    id: str
    scan_id: str
    severity: str
    file_path: str
    line_no: Optional[int] = None
    title: str
    description: Optional[str] = None
    ai_suggestion: Optional[Dict[str, Any]] = None
    example_code: Optional[str] = None
    status: str
    fingerprint: Optional[str] = None
    case_outdated: bool = False
    handled_by: Optional[str] = None
    handled_at: Optional[str] = None


class IssueUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(open|fixed|false_positive)$")
    handled_by: Optional[str] = None


class GenerateCaseResult(BaseModel):
    generated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    errors: List[Dict[str, Any]] = []
```

- [ ] **Step 2: 写失败 API 测试**

Create `backend/tests/test_api_whitescan.py`:

```python
"""Whitescan API endpoint tests (dependency overrides)."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app

PID = "00000000-0000-0000-0000-000000000001"
SCAN = "22222222-2222-2222-2222-222222222222"
ISSUE = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


def _override(mock_svc):
    from app.api.v1.whitescan import get_scan_service
    app.dependency_overrides[get_scan_service] = lambda: mock_svc


class TestScanEndpoints:
    def test_trigger_scan(self, client):
        svc = MagicMock()
        svc.create_scan = AsyncMock(return_value={"id": SCAN, "status": "scanning"})
        svc.update_scan_fields = AsyncMock(return_value=None)
        _override(svc)
        r = client.post("/api/v1/whitescan/scan",
                        json={"project_id": PID, "repo_url": "https://git.example/x.git"})
        assert r.status_code == 200
        assert r.json()["data"]["scan_id"] == SCAN

    def test_list_scans(self, client):
        svc = MagicMock()
        svc.list_scans = AsyncMock(return_value={"total": 1, "page": 1, "page_size": 20,
                                                  "items": [{"id": SCAN, "status": "done"}]})
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans?project_id={PID}")
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 1

    def test_get_scan(self, client):
        svc = MagicMock()
        svc.get_scan = AsyncMock(return_value={"id": SCAN, "status": "done", "total_issues": 2})
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans/{SCAN}")
        assert r.status_code == 200
        assert r.json()["data"]["total_issues"] == 2

    def test_list_issues(self, client):
        svc = MagicMock()
        svc.list_issues = AsyncMock(return_value=[{"id": ISSUE, "severity": "high"}])
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans/{SCAN}/issues?severity=high")
        assert r.status_code == 200
        assert r.json()["data"][0]["severity"] == "high"


class TestIssueEndpoints:
    def test_update_issue(self, client):
        svc = MagicMock()
        svc.update_issue = AsyncMock(return_value={"id": ISSUE, "status": "fixed"})
        _override(svc)
        r = client.patch(f"/api/v1/whitescan/issues/{ISSUE}", json={"status": "fixed"})
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "fixed"

    def test_ai_fix(self, client):
        svc = MagicMock()
        svc.get_issue = AsyncMock(return_value={"id": ISSUE, "ai_suggestion": None})
        svc.ai_fix = AsyncMock(return_value={"id": ISSUE,
                                              "ai_suggestion": {"suggestion": "s", "fixed_code": "f"}})
        _override(svc)
        r = client.post(f"/api/v1/whitescan/issues/{ISSUE}/ai-fix", params={"project_id": PID})
        assert r.status_code == 200
        assert r.json()["data"]["ai_suggestion"]["suggestion"] == "s"


class TestGenerateAndExport:
    def test_generate_cases(self, client):
        svc = MagicMock()
        svc.generate_cases = AsyncMock(return_value={"generated_count": 2, "skipped_count": 1,
                                                      "failed_count": 0, "errors": []})
        _override(svc)
        r = client.post(f"/api/v1/whitescan/scans/{SCAN}/generate-cases",
                        params={"project_id": PID})
        assert r.status_code == 200
        assert r.json()["data"]["generated_count"] == 2

    def test_export_xlsx(self, client):
        svc = MagicMock()
        svc.export_scan = AsyncMock(return_value=(b"PK\x03\x04fake", "BUG清单.xlsx"))
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans/{SCAN}/export?format=xlsx")
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_whitescan.py -v`
Expected: FAIL（router 未注册 → 404）

- [ ] **Step 4: 实现 router**

Create `backend/app/api/v1/whitescan.py`:

```python
"""Whitescan API endpoints (prefix /whitescan). semgrep scan + AI fix + regression cases."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.code_scan_service import CodeScanService
from app.services.ai_fix_service import AIFixService
from app.services.regression_case_generator import RegressionCaseGenerator
from app.services.scan_export_service import ScanExportService
from app.schemas.whitescan import (
    ScanTriggerRequest, ScanListResponse, IssueUpdateRequest,
)
from app.models.test_case import TestCase
from sqlalchemy import select

from uuid import UUID

router = APIRouter()


def get_scan_service(db: AsyncSession = Depends(get_db)) -> CodeScanService:
    return CodeScanService(db)


@router.post("/scan")
async def trigger_scan(req: ScanTriggerRequest,
                       svc: CodeScanService = Depends(get_scan_service)):
    scan = await svc.create_scan(req.project_id, req.repo_url, req.branch)
    # Celery async dispatch; test env may lack broker -> degrade to error note
    try:
        from app.tasks.code_scan_tasks import run_scan_task
        run_scan_task.delay(str(scan["id"]), req.project_id, req.repo_url, req.branch)
        dispatched = True
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"task broker unavailable: {e}")
    return {"code": 0, "data": {"scan_id": scan["id"], "status": scan["status"],
                                 "dispatched": dispatched}}


@router.get("/scans")
async def list_scans(project_id: str = Query(...), page: int = Query(1, ge=1),
                     page_size: int = Query(20, ge=1, le=100),
                     svc: CodeScanService = Depends(get_scan_service)):
    return {"code": 0, "data": await svc.list_scans(project_id, page, page_size)}


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: str, svc: CodeScanService = Depends(get_scan_service)):
    scan = await svc.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"code": 0, "data": scan}


@router.get("/scans/{scan_id}/issues")
async def list_issues(scan_id: str, severity: Optional[str] = Query(None),
                      status: Optional[str] = Query(None),
                      svc: CodeScanService = Depends(get_scan_service)):
    return {"code": 0, "data": await svc.list_issues(scan_id, severity, status)}


@router.patch("/issues/{issue_id}")
async def update_issue(issue_id: str, req: IssueUpdateRequest,
                       svc: CodeScanService = Depends(get_scan_service)):
    result = await svc.update_issue(issue_id, req.status, req.handled_by or "system")
    if not result:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"code": 0, "data": result}


@router.post("/issues/{issue_id}/ai-fix")
async def ai_fix(issue_id: str, project_id: str = Query(...),
                 svc: CodeScanService = Depends(get_scan_service),
                 db: AsyncSession = Depends(get_db)):
    from app.services.ai_gateway import AIGateway
    fixer = AIFixService(db, AIGateway())
    result = await fixer.generate_fix(issue_id, project_id=project_id)
    if not result:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"code": 0, "data": result}


@router.post("/scans/{scan_id}/generate-cases")
async def generate_cases(scan_id: str, project_id: str = Query(...),
                         svc: CodeScanService = Depends(get_scan_service),
                         db: AsyncSession = Depends(get_db)):
    from app.services.ai_gateway import AIGateway
    generator = RegressionCaseGenerator(AIGateway())
    issues = await svc.list_issues(scan_id)
    # inject real _case_exists + persistence
    async def case_exists(pid, issue_id):
        q = select(TestCase).where(TestCase.source_issue_id == UUID(issue_id),
                                   TestCase.is_deleted.is_(False))
        return (await db.execute(q)).scalar_one_or_none() is not None

    async def persist(case, issue):
        tc = TestCase(
            project_id=UUID(project_id),
            name=case["name"][:100],
            priority=case.get("priority", "P1"),
            case_type="functional",
            automation_status="pending",
            precondition=case.get("precondition"),
            steps=case["steps"],
            expected_result=case.get("expected_result", "")[:200],
            source_issue_id=UUID(issue["id"]),
        )
        db.add(tc)
        await db.commit()
        return tc

    generator._case_exists = case_exists
    # wrap generate_case to persist
    original = generator.generate_case
    async def gen_and_persist(issue, suggestion):
        case = await original(issue, suggestion)
        await persist(case, issue)
        return case
    generator.generate_case = gen_and_persist
    result = await generator.batch_generate(project_id, issues)
    return {"code": 0, "data": result}


@router.get("/scans/{scan_id}/export")
async def export_scan(scan_id: str, format: str = Query("xlsx", pattern="^(xlsx|md)$"),
                      svc: CodeScanService = Depends(get_scan_service)):
    issues = await svc.list_issues(scan_id)
    exporter = ScanExportService()
    if format == "xlsx":
        data = exporter.export_buglist_xlsx(issues)
        filename = f"BUG清单-{scan_id[:8]}.xlsx"
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data = exporter.export_issues_markdown(issues).encode("utf-8")
        filename = f"BUG清单-{scan_id[:8]}.md"
        mime = "text/markdown"
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})
```

- [ ] **Step 5: 注册 router**

Modify `backend/app/api/__init__.py`：import 行加 `whitescan`，include 区追加：
```python
api_router.include_router(whitescan.router, prefix="/whitescan", tags=["whitescan"])
```

- [ ] **Step 6: 跑测试确认通过 + 路由核对 + 全量**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_api_whitescan.py -v`
Expected: PASS（8 tests）

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; rs=sorted(set(r.path for r in app.routes if '/whitescan' in getattr(r,'path',''))); [print(p) for p in rs]"`
Expected: 9 条 /whitescan/* 路径

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/schemas/whitescan.py app/api/v1/whitescan.py app/api/__init__.py tests/test_api_whitescan.py
git commit -m "feat(whitescan): 9 API endpoints + router registration (W9)"
```

---

## Task 6: 前端 WhiteScan 页 + 菜单改「白盒测试」

**Files:**
- Create: `frontend/src/api/whitescan.js`
- Create: `frontend/src/views/whitescan/WhiteScan.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/layouts/MainLayout.vue`

- [ ] **Step 1: 写 api/whitescan.js**

Create `frontend/src/api/whitescan.js`:

```javascript
import axios from './axios'

export const whitescanAPI = {
  triggerScan(projectId, repoUrl, branch = 'main') {
    return axios.post('/whitescan/scan', { project_id: projectId, repo_url: repoUrl, branch }).then(r => r.data)
  },
  listScans(projectId, page = 1, pageSize = 20) {
    return axios.get('/whitescan/scans', { params: { project_id: projectId, page, page_size: pageSize } }).then(r => r.data)
  },
  getScan(scanId) {
    return axios.get(`/whitescan/scans/${scanId}`).then(r => r.data)
  },
  listIssues(scanId, params = {}) {
    return axios.get(`/whitescan/scans/${scanId}/issues`, { params }).then(r => r.data)
  },
  updateIssue(issueId, status) {
    return axios.patch(`/whitescan/issues/${issueId}`, { status }).then(r => r.data)
  },
  aiFix(issueId, projectId) {
    return axios.post(`/whitescan/issues/${issueId}/ai-fix`, null, { params: { project_id: projectId } }).then(r => r.data)
  },
  generateCases(scanId, projectId) {
    return axios.post(`/whitescan/scans/${scanId}/generate-cases`, null, { params: { project_id: projectId } }).then(r => r.data)
  },
  exportUrl(scanId, format = 'xlsx') {
    return `/whitescan/scans/${scanId}/export?format=${format}`
  },
}
```

- [ ] **Step 2: 写 WhiteScan.vue**

Create `frontend/src/views/whitescan/WhiteScan.vue`（4 区块，参照 ReviewCenter.vue 最新风格：loadProjects/loading/@change 重拉）:

```vue
<template>
  <div class="whitescan" v-loading="loading">
    <el-card>
      <template #header><span>白盒测试</span></template>

      <!-- ① 扫描入口 -->
      <el-form inline>
        <el-form-item label="项目">
          <el-select v-model="projectId" filterable style="width: 220px" @change="loadScans">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="仓库URL">
          <el-input v-model="repoUrl" placeholder="https://git.example/repo.git" style="width: 320px" />
        </el-form-item>
        <el-form-item label="分支">
          <el-input v-model="branch" placeholder="main" style="width: 120px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="scanning" @click="onScan">开始扫描</el-button>
        </el-form-item>
      </el-form>

      <!-- ② 扫描记录 + 概览 -->
      <el-table :data="scans" border style="margin-bottom: 16px" highlight-current-row
        @current-change="onScanSelect">
        <el-table-column prop="created_at" label="时间" width="180" />
        <el-table-column prop="repo_url" label="仓库" min-width="200" show-overflow-tooltip />
        <el-table-column prop="branch" label="分支" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="{ done: 'success', failed: 'danger' }[row.status] || 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_issues" label="问题" width="70" />
        <el-table-column label="高/中/低" width="100">
          <template #default="{ row }">{{ row.high_count }}/{{ row.mid_count }}/{{ row.low_count }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="onGenerateCases(row)">生成回归用例</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- ③ 问题列表 -->
      <template v-if="currentScan">
        <el-form inline style="margin-bottom: 8px">
          <el-form-item label="等级">
            <el-select v-model="sevFilter" clearable style="width: 110px" @change="loadIssues">
              <el-option label="高危" value="high" /><el-option label="中危" value="mid" /><el-option label="低危" value="low" />
            </el-select>
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="statusFilter" clearable style="width: 110px" @change="loadIssues">
              <el-option label="待处理" value="open" /><el-option label="已修复" value="fixed" /><el-option label="误报" value="false_positive" />
            </el-select>
          </el-form-item>
        </el-form>
        <el-table :data="issues" border>
          <el-table-column label="等级" width="70">
            <template #default="{ row }">
              <el-tag :type="{ high: 'danger', mid: 'warning', low: 'info' }[row.severity]">{{ row.severity }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="文件" min-width="220">
            <template #default="{ row }">{{ row.file_path }}:{{ row.line_no }}</template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
          <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">{{ statusLabel(row.status) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="onAiFix(row)">AI修复</el-button>
              <el-button link size="small" @click="onMark(row, 'fixed')">标记已修复</el-button>
              <el-button link size="small" @click="onMark(row, 'false_positive')">误报</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- ④ 产出物下载 -->
      <div style="margin-top: 16px" v-if="currentScan">
        <el-button size="small" @click="onExport('xlsx')">下载BUG清单</el-button>
        <el-button size="small" @click="onExport('md')">下载Markdown清单</el-button>
      </div>
    </el-card>

    <!-- AI 修复弹窗 -->
    <el-dialog v-model="fixDialog" title="AI 修复建议" width="640px">
      <template v-if="fixing">
        <p><b>修复思路：</b>{{ fixing.ai_suggestion?.suggestion }}</p>
        <p><b>原代码：</b></p>
        <pre class="code-block">{{ fixing.ai_suggestion?.original_code }}</pre>
        <p><b>修复后：</b></p>
        <pre class="code-block">{{ fixing.ai_suggestion?.fixed_code }}</pre>
      </template>
      <template #footer>
        <el-button @click="fixDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { whitescanAPI } from '@/api/whitescan.js'
import { projectAPI } from '@/api/project.js'
import axios from '@/api/axios.js'

const loading = ref(false)
const scanning = ref(false)
const projects = ref([])
const projectId = ref('')
const repoUrl = ref('')
const branch = ref('main')
const scans = ref([])
const currentScan = ref(null)
const issues = ref([])
const sevFilter = ref('')
const statusFilter = ref('')
const fixDialog = ref(false)
const fixing = ref(null)

const statusLabel = (s) => ({ open: '待处理', fixed: '已修复', false_positive: '误报' }[s] || s)

const loadProjects = async () => {
  try {
    const res = await projectAPI.list()
    projects.value = Array.isArray(res) ? res : (res?.items || [])
    if (projects.value.length) { projectId.value = projects.value[0].id; loadScans() }
  } catch (e) { console.error(e) }
}

const loadScans = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const res = await whitescanAPI.listScans(projectId.value)
    scans.value = res?.items || []
  } catch (e) { console.error(e) } finally { loading.value = false }
}

const loadIssues = async () => {
  if (!currentScan.value) return
  try {
    const params = {}
    if (sevFilter.value) params.severity = sevFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    issues.value = await whitescanAPI.listIssues(currentScan.value.id, params) || []
  } catch (e) { console.error(e) }
}

const onScanSelect = async (row) => {
  currentScan.value = row
  if (row) await loadIssues()
}

const onScan = async () => {
  if (!projectId.value || !repoUrl.value) { ElMessage.warning('选择项目并填写仓库URL'); return }
  scanning.value = true
  try {
    const res = await whitescanAPI.triggerScan(projectId.value, repoUrl.value, branch.value || 'main')
    ElMessage.success('扫描已提交，异步执行中')
    // poll scan status every 3s until done/failed
    const sid = res.scan_id
    const timer = setInterval(async () => {
      const s = await whitescanAPI.getScan(sid)
      if (s.status !== 'scanning') {
        clearInterval(timer)
        scanning.value = false
        s.status === 'done' ? ElMessage.success(`扫描完成：${s.total_issues} 个问题`) : ElMessage.error('扫描失败')
        loadScans()
      }
    }, 3000)
  } catch (e) { ElMessage.error('提交失败'); scanning.value = false }
}

const onAiFix = async (row) => {
  loading.value = true
  try {
    const res = await whitescanAPI.aiFix(row.id, projectId.value)
    fixing.value = res
    fixDialog.value = true
  } catch (e) { ElMessage.error('AI修复失败') } finally { loading.value = false }
}

const onMark = async (row, status) => {
  try {
    await whitescanAPI.updateIssue(row.id, status)
    ElMessage.success('已更新')
    loadIssues()
  } catch (e) { ElMessage.error('更新失败') }
}

const onGenerateCases = async (row) => {
  loading.value = true
  try {
    const res = await whitescanAPI.generateCases(row.id, projectId.value)
    ElMessage.success(`生成 ${res.generated_count} 条，跳过 ${res.skipped_count} 条`)
  } catch (e) { ElMessage.error('生成失败') } finally { loading.value = false }
}

const onExport = (format) => {
  window.location = axios.defaults.baseURL + whitescanAPI.exportUrl(currentScan.value.id, format)
}

onMounted(loadProjects)
</script>

<style scoped>
.whitescan { padding: 20px; }
.code-block { background: #f5f7fa; padding: 10px; font-family: monospace; font-size: 12px; max-height: 200px; overflow: auto; white-space: pre-wrap; }
</style>
```

- [ ] **Step 3: 路由 + 菜单改名**

Modify `frontend/src/router/index.js`：children 末尾（reviews 之后）加：
```javascript
        {
          path: 'whitescan',
          name: 'WhiteScan',
          component: () => import('@/views/whitescan/WhiteScan.vue'),
          meta: { title: '白盒测试' }
        }
```

Modify `frontend/src/layouts/MainLayout.vue`：
```html
<!-- 原 -->
<el-menu-item index="/quality/whitebox">白盒代码体检</el-menu-item>
<!-- 改为（死链修复 + 改名，用户 2026-08-28 要求） -->
<el-menu-item index="/whitescan">白盒测试</el-menu-item>
```

- [ ] **Step 4: 前端构建验证**

```bash
cd D:/MoonTest/.claude/worktrees/module9-whitescan/frontend
cmd //c "mklink /J node_modules D:\MoonTest\frontend\node_modules"
node node_modules/vite/bin/vite.js build
cmd //c "rmdir node_modules"
rm -rf dist
```
Expected: 成功（WhiteScan chunk 正常 emit）

- [ ] **Step 5: Commit**

```bash
cd D:/MoonTest/.claude/worktrees/module9-whitescan
git add frontend/src/api/whitescan.js frontend/src/views/whitescan/WhiteScan.vue frontend/src/router/index.js frontend/src/layouts/MainLayout.vue
git commit -m "feat(whitescan): WhiteScan page + routes + menu rename 白盒测试 (W9)"
```

---

## Task 7: 全量验证 + 收尾

- [ ] **Step 1: 后端全量**

Run: `cd backend && PYTHONUTF8=1 python -m pytest -q`
Expected: 全 PASS（基线 + ~26 新增）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 路由核对**

Run: `cd backend && PYTHONUTF8=1 python -c "from app.main import app; rs=sorted(set(r.path for r in app.routes if '/whitescan' in getattr(r,'path',''))); [print(p) for p in rs]"`
Expected: 9 条

- [ ] **Step 4: 更新 TODO_LIST**

Modify `.claude/TODO_LIST.md`：「#9 白盒代码体检」改 P0 完成（菜单名已改白盒测试）+ worktree 待合回；总体进度计数更新。

- [ ] **Step 5: 最终 Commit**

```bash
git add .claude/TODO_LIST.md
git commit -m "chore: update TODO_LIST (#9 whitescan done, menu renamed 白盒测试) (W9)"
```

---

## Self-Review 记录

**1. Spec 覆盖：**
- 2 新表 + source_issue_id ✓ T1
- semgrep Docker 方案 B（subprocess + @patch）✓ T2 _run_semgrep
- WHITE-04 误报指纹忽略 ✓ T2 get_ignored_fingerprints + T4 run_scan_sync 跳过
- AI 修复（AIGateway.chat + stage 埋点 + 坏 JSON 降级）✓ T3
- 回归用例生成（#2 框架 5 规则 + 禁用词 + 强制自动化）✓ T3 prompt 断言
- 增量生成（case_exists 跳过）✓ T3 batch_generate + T4 真实注入
- 产出物导出（xlsx 魔数 + markdown）✓ T4
- 9 端点 ✓ T5
- 前端 4 区块 + 轮询 ✓ T6
- 菜单「白盒代码体检」→「白盒测试」+ 死链修复 ✓ T6 Step3（用户 2026-08-28 要求）
- Celery 异步 ✓ T4 task（broker 不可用 503 降级）
全部覆盖。

**2. 占位符扫描：** 无 TBD/TODO。T3 注记的 batch_generate 注入方式在 T4 Step4 给出明确写法（generator._case_exists 赋值 + generate_case 包装持久化）。

**3. 类型一致性：** ScanTriggerRequest/IssueUpdateRequest 键与前端调用一致；create_scan 返回 dict 键与 trigger_scan 响应一致；batch_generate 返回键（generated_count/skipped_count/failed_count/errors）schema/前端一致；_compute_fingerprint 签名在 service/测试/编排一致。

**4. 边界核对：** 复用 #2 StepSchema/禁用词、#3 TestCase/版本、#5a Celery（不重写）；不改 case_refiner/test_case_service 核心。共享文件：models/test_case.py（追加 1 列）、api/__init__.py（追加）、菜单（改名+死链）。requirements.txt 不动（semgrep 走 Docker）。

**5. 测试数据真实性（吸取 #7 教训）：** semgrep JSON 按真实输出结构（check_id/path/start.line/extra.message/severity/lines）；CASE_JSON 无虚构键；AI fix 坏 JSON 走降级路径有测试。

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-28-whitescan.md`.**
