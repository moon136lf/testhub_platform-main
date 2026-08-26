"""Execution query service: read-only aggregation over execution_record/execution_detail."""
import logging
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionRecord, ExecutionDetail

logger = logging.getLogger(__name__)


class ExecutionQueryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_records(self, project_id: str, *, exec_type: Optional[str] = None,
                          days: int = 7, page: int = 1, page_size: int = 20) -> dict:
        pid = UUID(project_id)
        since = datetime.now(timezone.utc) - timedelta(days=days)
        base = select(ExecutionRecord).where(
            ExecutionRecord.project_id == pid,
            ExecutionRecord.started_at >= since,
        )
        if exec_type:
            base = base.where(ExecutionRecord.exec_type == exec_type)

        total_q = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(total_q)).scalar() or 0

        rows_q = base.order_by(ExecutionRecord.started_at.desc()).offset(
            (page - 1) * page_size).limit(page_size)
        rows = (await self.db.execute(rows_q)).scalars().all()
        return {"total": total, "page": page, "page_size": page_size,
                "items": [r.to_dict() for r in rows]}

    async def get_detail(self, exec_id: str) -> Optional[dict]:
        rec_q = select(ExecutionRecord).where(ExecutionRecord.exec_id == exec_id)
        rec = (await self.db.execute(rec_q)).scalar_one_or_none()
        if not rec:
            return None

        fail_count_q = select(func.count()).select_from(ExecutionDetail).where(
            ExecutionDetail.execution_record_id == rec.id,
            ExecutionDetail.status == "fail",
        )
        fail_step_count = (await self.db.execute(fail_count_q)).scalar() or 0

        details_q = (select(ExecutionDetail)
                     .where(ExecutionDetail.execution_record_id == rec.id,
                            ExecutionDetail.status == "fail")
                     .order_by(ExecutionDetail.step))
        details = (await self.db.execute(details_q)).scalars().all()

        return {
            "record": rec.to_dict(),
            "fail_step_count": fail_step_count,
            "total_duration_ms": rec.duration_ms or 0,
            "token_remaining": None,
            "details": [d.to_dict() for d in details],
        }

    async def list_details(self, exec_id: str, *, status: Optional[str] = "fail") -> list:
        rec_q = select(ExecutionRecord).where(ExecutionRecord.exec_id == exec_id)
        rec = (await self.db.execute(rec_q)).scalar_one_or_none()
        if not rec:
            return []
        q = select(ExecutionDetail).where(ExecutionDetail.execution_record_id == rec.id)
        if status:
            q = q.where(ExecutionDetail.status == status)
        q = q.order_by(ExecutionDetail.step)
        rows = (await self.db.execute(q)).scalars().all()
        return [r.to_dict() for r in rows]

    async def get_trend(self, project_id: str, days: int = 7) -> list:
        pid = UUID(project_id)
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (
            select(
                func.date_trunc("day", ExecutionRecord.started_at).label("d"),
                func.avg(ExecutionRecord.pass_rate).label("avg_rate"),
                func.count().label("cnt"),
            )
            .where(ExecutionRecord.project_id == pid, ExecutionRecord.started_at >= since)
            .group_by("d").order_by("d")
        )
        rows = (await self.db.execute(q)).all()
        return [
            {"date": str(r[0].date()) if r[0] and hasattr(r[0], "date") else (str(r[0]) if r[0] else ""),
             "pass_rate": float(r[1]) if r[1] is not None else 0.0,
             "exec_count": r[2]}
            for r in rows
        ]
