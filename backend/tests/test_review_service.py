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
