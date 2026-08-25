"""Token quota + status aggregation + warning (req §11.4 / §9.2.6)."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import TokenQuota
from app.models.execution import AICallLog
from app.core.config import settings
from app.schemas.system import TokenStatusResponse, TokenUsageItem, TokenUsageResponse

logger = logging.getLogger(__name__)


class TokenService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_quota(self, project_id: str) -> dict:
        q = select(TokenQuota).where(TokenQuota.project_id == UUID(project_id))
        row = (await self.db.execute(q)).scalar_one_or_none()
        if not row:
            return {
                "project_id": project_id, "total_quota": settings.TOKEN_QUOTA,
                "alert_threshold": int(settings.TOKEN_WARNING_RATE * 100),
                "updated_at": None,
            }
        return row.to_dict()

    async def update_quota(self, project_id: str, *,
                           total_quota: Optional[int] = None,
                           alert_threshold: Optional[int] = None) -> dict:
        q = select(TokenQuota).where(TokenQuota.project_id == UUID(project_id))
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            row = TokenQuota(
                project_id=UUID(project_id),
                total_quota=total_quota if total_quota is not None else settings.TOKEN_QUOTA,
                alert_threshold=alert_threshold if alert_threshold is not None else int(settings.TOKEN_WARNING_RATE * 100),
            )
            self.db.add(row)
        else:
            if total_quota is not None:
                row.total_quota = total_quota
            if alert_threshold is not None:
                row.alert_threshold = alert_threshold
        await self.db.commit()
        await self.db.refresh(row)
        return row.to_dict()

    async def get_status(self, project_id: str) -> TokenStatusResponse:
        """Aggregate token usage status (§9.2.6)."""
        pid = UUID(project_id)
        # 1. quota
        q = select(TokenQuota).where(TokenQuota.project_id == pid)
        quota = (await self.db.execute(q)).scalar_one_or_none()
        total = quota.total_quota if quota else settings.TOKEN_QUOTA
        threshold = quota.alert_threshold if quota else int(settings.TOKEN_WARNING_RATE * 100)

        # 2. total used (SUM)
        used_q = select(func.coalesce(func.sum(AICallLog.tokens_used), 0)).where(
            AICallLog.project_id == pid
        )
        used = (await self.db.execute(used_q)).scalar() or 0

        # 3. recent 7-day sum
        since = datetime.now(timezone.utc) - timedelta(days=7)
        recent_q = select(func.coalesce(func.sum(AICallLog.tokens_used), 0)).where(
            AICallLog.project_id == pid,
            AICallLog.created_at >= since,
        )
        recent_7d = (await self.db.execute(recent_q)).scalar() or 0
        daily_avg = recent_7d / 7.0

        remaining = max(0, total - used)
        percentage = (used / total * 100) if total > 0 else 0.0
        is_warning = (remaining / total * 100) <= threshold if total > 0 else False
        est_days = int(remaining / daily_avg) if daily_avg > 0 else None

        return TokenStatusResponse(
            total_quota=total, used=used, remaining=remaining,
            percentage=round(percentage, 2), is_warning=is_warning,
            warning_threshold=threshold, recent_daily_avg=round(daily_avg, 2),
            estimated_days_remaining=est_days,
        )

    async def get_usage(self, project_id: str, days: int = 7) -> TokenUsageResponse:
        """Usage breakdown by stage / model / day for charts."""
        pid = UUID(project_id)
        since = datetime.now(timezone.utc) - timedelta(days=days)

        by_stage_q = (
            select(AICallLog.stage, func.coalesce(func.sum(AICallLog.tokens_used), 0))
            .where(AICallLog.project_id == pid, AICallLog.created_at >= since)
            .group_by(AICallLog.stage)
        )
        by_model_q = (
            select(AICallLog.model, func.coalesce(func.sum(AICallLog.tokens_used), 0))
            .where(AICallLog.project_id == pid, AICallLog.created_at >= since)
            .group_by(AICallLog.model)
        )
        by_stage = [
            TokenUsageItem(label=r[0] or "unknown", tokens=r[1])
            for r in (await self.db.execute(by_stage_q)).all()
        ]
        by_model = [
            TokenUsageItem(label=r[0] or "unknown", tokens=r[1])
            for r in (await self.db.execute(by_model_q)).all()
        ]

        # daily buckets
        daily_q = (
            select(
                func.date_trunc("day", AICallLog.created_at).label("d"),
                func.coalesce(func.sum(AICallLog.tokens_used), 0),
            )
            .where(AICallLog.project_id == pid, AICallLog.created_at >= since)
            .group_by("d").order_by("d")
        )
        daily = [
            {"date": str(r[0].date()) if r[0] else "", "tokens": r[1]}
            for r in (await self.db.execute(daily_q)).all()
        ]
        return TokenUsageResponse(by_stage=by_stage, by_model=by_model, daily=daily)
