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
