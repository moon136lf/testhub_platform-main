"""OperationLogService tests."""
import pytest
from unittest.mock import AsyncMock, Mock

from app.services.operation_log_service import OperationLogService, log_operation


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = Mock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_log_operation_persists(mock_db):
    svc = OperationLogService(mock_db)
    await svc.log("system", "update_setting", target_type="setting", target_id="heal.strategy",
                  detail={"old": "HEURISTIC", "new": "SMART"}, operator="admin", ip="127.0.0.1")
    assert mock_db.add.called
    added = mock_db.add.call_args[0][0]
    assert added.module == "system"
    assert added.action == "update_setting"
    assert added.detail["new"] == "SMART"
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_log_failure_does_not_raise(mock_db):
    """Log failure must not break the caller's flow."""
    mock_db.commit.side_effect = Exception("db down")
    svc = OperationLogService(mock_db)
    # should NOT raise
    await svc.log("system", "x", target_type=None, target_id=None,
                  detail=None, operator=None, ip=None)


@pytest.mark.asyncio
async def test_module_level_helper(mock_db, monkeypatch):
    """log_operation module helper wraps the service."""
    called = {}
    class FakeFactory:
        def __call__(self, db):
            svc = OperationLogService(db)
            svc.log = AsyncMock(return_value=None)
            called["svc"] = svc
            return svc
    import app.services.operation_log_service as mod
    monkeypatch.setattr(mod, "_build_service", FakeFactory())
    await log_operation(mock_db, "system", "create_env", "test_env", "1", {"name": "dev"}, "admin")
    assert called["svc"].log.called
