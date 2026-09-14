"""Execution query service: read-only aggregation over execution_record/execution_detail."""
import logging
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionRecord, ExecutionDetail, ExecutionBug

logger = logging.getLogger(__name__)


class ExecutionQueryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_records(self, project_id: str, *, exec_type: Optional[str] = None,
                          days: int = 7, page: int = 1, page_size: int = 20,
                          test_set_id: Optional[UUID] = None) -> dict:
        pid = UUID(project_id)
        since = datetime.now(timezone.utc) - timedelta(days=days)
        base = select(ExecutionRecord).where(
            ExecutionRecord.project_id == pid,
            ExecutionRecord.started_at >= since,
            ExecutionRecord.is_deleted.is_(False),
        )
        if exec_type:
            base = base.where(ExecutionRecord.exec_type == exec_type)
        if test_set_id:
            base = base.where(ExecutionRecord.test_set_id == test_set_id)

        total_q = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(total_q)).scalar() or 0

        rows_q = base.order_by(ExecutionRecord.started_at.desc()).offset(
            (page - 1) * page_size).limit(page_size)
        rows = (await self.db.execute(rows_q)).scalars().all()
        return {"total": total, "page": page, "page_size": page_size,
                "items": [r.to_dict() for r in rows]}

    async def set_trend(self, test_set_id, limit: int = 10) -> list:
        """某测试集最近 limit 次执行趋势（通过率/状态/时间）。"""
        rows = (await self.db.execute(
            select(ExecutionRecord.pass_rate, ExecutionRecord.status, ExecutionRecord.started_at)
            .where(ExecutionRecord.test_set_id == test_set_id,
                   ExecutionRecord.is_deleted.is_(False))
            .order_by(ExecutionRecord.started_at.desc()).limit(limit))).all()
        return [{"pass_rate": float(r[0] or 0), "status": r[1],
                 "started_at": r[2].isoformat() if r[2] else None} for r in rows]

    async def list_set_records(self, test_set_id, *, page: int = 1, page_size: int = 20,
                               result: str = "all") -> dict:
        """测试集关联的执行记录（result: all/success/failed）。

        ExecutionRecord.status 实际枚举：running / done（script_tasks 写入）。
        failed 判定：status != 'done' 或 fail_count > 0。
        """
        tid = test_set_id if isinstance(test_set_id, UUID) else UUID(str(test_set_id))
        base = select(ExecutionRecord).where(
            ExecutionRecord.test_set_id == tid,
            ExecutionRecord.is_deleted.is_(False),
        )
        if result == "success":
            base = base.where(ExecutionRecord.status == "done",
                              ExecutionRecord.fail_count == 0)
        elif result == "failed":
            base = base.where((ExecutionRecord.status != "done")
                              & (ExecutionRecord.status != "running")
                              | (ExecutionRecord.fail_count > 0))

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

        bugs_q = (select(ExecutionBug)
                  .where(ExecutionBug.record_id == rec.id)
                  .order_by(ExecutionBug.created_at))
        bugs = (await self.db.execute(bugs_q)).scalars().all()

        return {
            "record": rec.to_dict(),
            "fail_step_count": fail_step_count,
            "total_duration_ms": rec.duration_ms or 0,
            "token_remaining": None,
            "details": [d.to_dict() for d in details],
            "bugs": [b.to_dict() for b in bugs],
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
        # pass_rate weighted by total_cases per spec §3.1 (a 1-case 100% run must
        # not outweigh a 100-case 80% run). NULLIF guards divide-by-zero.
        q = (
            select(
                func.date_trunc("day", ExecutionRecord.started_at).label("d"),
                (func.sum(ExecutionRecord.pass_rate * ExecutionRecord.total_cases)
                 / func.nullif(func.sum(ExecutionRecord.total_cases), 0)).label("avg_rate"),
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
