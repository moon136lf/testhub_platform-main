"""TokenService tests — pure arithmetic with mocked db."""
import pytest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.services.token_service import TokenService


def _mock_scalar(value):
    """Mock a result whose .scalar() returns value."""
    return Mock(scalar=Mock(return_value=value))


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = Mock()
    return db


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_basic_status_no_warning(self, mock_db):
        pid = str(uuid4())
        # 1st execute: token_quota row -> total 100000, threshold 10
        quota_row = Mock(); quota_row.total_quota = 100000; quota_row.alert_threshold = 10
        # 2nd: SUM tokens_used -> 5000
        # 3rd: recent 7-day sum -> 7000
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=quota_row)),
            _mock_scalar(5000),
            _mock_scalar(7000),
        ]
        svc = TokenService(mock_db)
        st = await svc.get_status(pid)
        assert st.total_quota == 100000
        assert st.used == 5000
        assert st.remaining == 95000
        assert st.percentage == pytest.approx(5.0, abs=0.01)
        assert st.is_warning is False
        assert st.recent_daily_avg == pytest.approx(1000.0, abs=0.01)
        assert st.estimated_days_remaining == 95

    @pytest.mark.asyncio
    async def test_warning_when_below_threshold(self, mock_db):
        pid = str(uuid4())
        quota_row = Mock(); quota_row.total_quota = 100000; quota_row.alert_threshold = 10
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=quota_row)),
            _mock_scalar(95000),  # used 95000 -> remaining 5000 -> 5% <= 10% -> warning
            _mock_scalar(7000),
        ]
        svc = TokenService(mock_db)
        st = await svc.get_status(pid)
        assert st.is_warning is True
        assert st.remaining == 5000

    @pytest.mark.asyncio
    async def test_no_quota_row_uses_default(self, mock_db):
        """No token_quota row -> default 100000 from settings.TOKEN_QUOTA."""
        pid = str(uuid4())
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=None)),
            _mock_scalar(0),
            _mock_scalar(0),
        ]
        svc = TokenService(mock_db)
        st = await svc.get_status(pid)
        assert st.total_quota == 100000
        assert st.used == 0
        assert st.is_warning is False
        # daily avg 0 -> estimated_days_remaining None
        assert st.estimated_days_remaining is None

    @pytest.mark.asyncio
    async def test_zero_usage_no_warning(self, mock_db):
        pid = str(uuid4())
        quota_row = Mock(); quota_row.total_quota = 100000; quota_row.alert_threshold = 10
        mock_db.execute.side_effect = [
            Mock(scalar_one_or_none=Mock(return_value=quota_row)),
            _mock_scalar(0),
            _mock_scalar(0),
        ]
        svc = TokenService(mock_db)
        st = await svc.get_status(pid)
        assert st.used == 0
        assert st.is_warning is False


class TestQuotaUpsert:
    @pytest.mark.asyncio
    async def test_update_quota_creates_if_missing(self, mock_db):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = TokenService(mock_db)
        await svc.update_quota(str(uuid4()), total_quota=200000, alert_threshold=15)
        assert mock_db.add.called
        added = mock_db.add.call_args[0][0]
        assert added.total_quota == 200000
        assert added.alert_threshold == 15

    @pytest.mark.asyncio
    async def test_update_quota_updates_existing(self, mock_db):
        row = Mock(); row.total_quota = 100000; row.alert_threshold = 10
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row))
        svc = TokenService(mock_db)
        await svc.update_quota(str(uuid4()), total_quota=500000)
        assert row.total_quota == 500000
        assert row.alert_threshold == 10  # unchanged
        assert not mock_db.add.called


class TestGetUsage:
    @pytest.mark.asyncio
    async def test_usage_breakdown_with_none_fallbacks(self, mock_db):
        """get_usage maps None stage/model -> 'unknown' and None date -> ''."""
        from datetime import datetime, timezone
        d = datetime(2026, 8, 25, tzinfo=timezone.utc)
        # by_stage rows: (stage, sum) — one None stage
        # by_model rows: (model, sum)
        # daily rows: (date_trunc, sum) — one None date
        stage_rows = [(None, 300), ("identify_point", 700)]
        model_rows = [("glm-4", 1000)]
        daily_rows = [(d, 1000), (None, 500)]
        mock_db.execute.side_effect = [
            Mock(all=Mock(return_value=stage_rows)),
            Mock(all=Mock(return_value=model_rows)),
            Mock(all=Mock(return_value=daily_rows)),
        ]
        svc = TokenService(mock_db)
        usage = await svc.get_usage(str(uuid4()), days=7)
        # None stage -> "unknown"
        labels = {item.label: item.tokens for item in usage.by_stage}
        assert labels["unknown"] == 300
        assert labels["identify_point"] == 700
        # model passthrough
        assert {item.label: item.tokens for item in usage.by_model} == {"glm-4": 1000}
        # None date -> "" ; valid date -> "2026-08-25"
        daily = {entry["date"]: entry["tokens"] for entry in usage.daily}
        assert daily["2026-08-25"] == 1000
        assert daily[""] == 500
