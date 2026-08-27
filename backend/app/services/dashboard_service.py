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
                "date": r[0].date().isoformat() if r[0] else "",
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
