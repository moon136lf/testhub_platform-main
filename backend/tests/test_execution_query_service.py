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
            _mock_scalar(5),
            _mock_scalars([r]),
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
        rows = [("2026-08-25", 92.5, 3), ("2026-08-24", 85.0, 5)]
        mock_db.execute.return_value = Mock(all=Mock(return_value=rows))
        svc = ExecutionQueryService(mock_db)
        result = await svc.get_trend(str(uuid4()), days=7)
        assert len(result) == 2
        assert result[0]["date"] == "2026-08-25"
        assert result[0]["pass_rate"] == 92.5
        assert result[0]["exec_count"] == 3

    @pytest.mark.asyncio
    async def test_trend_handles_real_datetime_rows(self, mock_db):
        # Real DB returns datetime from date_trunc, not a bare string.
        # Covers the r[0].date() branch (the hasattr shim is mock-compat only).
        from datetime import datetime as _dt
        d1 = _dt(2026, 8, 25, 0, 0, 0)
        d2 = _dt(2026, 8, 24, 0, 0, 0)
        rows = [(d1, 90.0, 2), (d2, 70.0, 4)]
        mock_db.execute.return_value = Mock(all=Mock(return_value=rows))
        svc = ExecutionQueryService(mock_db)
        result = await svc.get_trend(str(uuid4()), days=7)
        assert result[0]["date"] == "2026-08-25"
        assert result[1]["date"] == "2026-08-24"
        assert result[0]["pass_rate"] == 90.0
