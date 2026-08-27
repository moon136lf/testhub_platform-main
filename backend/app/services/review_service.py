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
        # defensive: skip rows without an actual report (DB IS NOT NULL may
        # still yield empty dicts; plan test expects unrefined rows skipped)
        valid_cases = [c for c in cases if c.refinement_report]
        for c in valid_cases:
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
            "case_count": len(valid_cases),
            "refined_at": refined_at,
            "suggestions": suggestions,
        }

    async def batch_update_review(self, project_id: str, case_ids: List[str],
                                  review_status: str,
                                  review_comment: Optional[str] = None) -> dict:
        """Batch update review_status/comment (REVIEW-01 flow). Only touches
        cases in the project."""
        pid = UUID(project_id)
        try:
            id_list = [UUID(c) for c in case_ids]
        except (ValueError, TypeError):
            id_list = []
        q = select(TestCase).where(
            TestCase.project_id == pid,
            TestCase.id.in_(id_list),
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
