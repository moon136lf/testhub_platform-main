"""W3 version history tests."""
import pytest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.models.test_case import CaseVersion, TestCase
from app.services.test_case_service import TestCaseService
from app.schemas.test_case import CaseUpdateRequest


def test_case_version_model_fields():
    cols = {c.name for c in CaseVersion.__table__.columns}
    assert {"id", "case_id", "version", "snapshot", "diff_summary", "changed_by", "created_at"} <= cols
    snap = CaseVersion.__table__.c.snapshot
    assert snap.type.__class__.__name__ == "JSONB"


def test_case_version_registered_in_models_init():
    import app.models as m
    assert hasattr(m, "CaseVersion")


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    db.add = Mock()
    return db


def _make_case(**kw):
    case = Mock()
    case.id = kw.get("id", uuid4())
    case.project_id = kw.get("project_id", uuid4())
    case.name = kw.get("name", "c")
    case.priority = kw.get("priority", "P1")
    case.case_type = kw.get("case_type", "functional")
    case.automation_status = kw.get("automation_status", "pending")
    case.precondition = kw.get("precondition", "")
    case.steps = kw.get("steps", [{"step": 1, "action": "a", "expected": "e"}])
    case.expected_result = kw.get("expected_result", "r")
    case.is_finalized = kw.get("is_finalized", False)
    case.version = kw.get("version", 1)
    case.hallucination_status = kw.get("hallucination_status", "normal")
    case.created_by = kw.get("created_by", "u")
    case.is_deleted = False
    case.created_at = case.updated_at = None
    return case


class TestSnapshotOnUpdate:
    @pytest.mark.asyncio
    async def test_update_writes_snapshot_before_change(self, mock_db):
        case = _make_case(version=1, steps=[{"step": 1, "action": "old", "expected": "old"}])
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=case))

        svc = TestCaseService(mock_db)
        req = CaseUpdateRequest(steps=[{"step": 1, "action": "new", "expected": "new"}])

        await svc.update_case(str(case.id), req)

        # a CaseVersion was added with version=1 and old steps snapshot
        added = [c for c in mock_db.add.call_args_list if isinstance(c.args[0], CaseVersion)]
        assert len(added) == 1
        assert added[0].args[0].version == 1
        assert added[0].args[0].snapshot["steps"][0]["action"] == "old"
        # case version incremented
        assert case.version == 2


class TestRollback:
    @pytest.mark.asyncio
    async def test_rollback_restores_snapshot_and_increments_version(self, mock_db):
        case = _make_case(version=3, steps=[{"step": 1, "action": "current", "expected": "c"}])
        snapshot_row = Mock()
        snapshot_row.version = 2
        snapshot_row.snapshot = {
            "name": "c", "priority": "P1", "case_type": "functional", "automation_status": "pending",
            "precondition": "", "steps": [{"step": 1, "action": "old", "expected": "o"}],
            "expected_result": "r",
        }
        # first execute returns the case, second returns the version snapshot
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=case)),
            Mock(scalar_one_or_none=Mock(return_value=snapshot_row)),
        ]

        svc = TestCaseService(mock_db)
        result = await svc.rollback_case(str(case.id), 2)

        assert case.steps == snapshot_row.snapshot["steps"]
        assert case.version == 4  # incremented, not decremented
        assert result is not None

        # 回滚动作本身记了一条新快照
        added = [c for c in mock_db.add.call_args_list if isinstance(c.args[0], CaseVersion)]
        assert len(added) == 1
        assert added[0].args[0].version == 4
        assert "回滚到 v2" in (added[0].args[0].diff_summary or "")


class TestVersionList:
    @pytest.mark.asyncio
    async def test_list_versions_returns_desc(self, mock_db):
        v1 = Mock(); v1.version = 1; v1.created_at = None; v1.changed_by = "a"
        v2 = Mock(); v2.version = 2; v2.created_at = None; v2.changed_by = "b"
        mock_db.execute.return_value = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[v2, v1]))))
        svc = TestCaseService(mock_db)
        result = await svc.list_versions(str(uuid4()))
        assert result[0].version == 2  # desc order preserved from query
