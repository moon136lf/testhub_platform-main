"""Operation log service. Best-effort: logging failure must not break callers."""
import logging
from typing import Optional, Any, List, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import OperationLog

logger = logging.getLogger(__name__)


class OperationLogService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, module: Optional[str] = None, page: int = 1,
                   page_size: int = 20) -> Tuple[List[dict], int]:
        """Return (items, total) for paginated operation logs."""
        q = select(OperationLog)
        total_q = select(func.count()).select_from(OperationLog)
        if module:
            q = q.where(OperationLog.module == module)
            total_q = total_q.where(OperationLog.module == module)
        rows = (await self.db.execute(
            q.order_by(OperationLog.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
        total = (await self.db.execute(total_q)).scalar() or 0
        return [r.to_dict() for r in rows], total

    async def log(self, module: str, action: str, *,
                  target_type: Optional[str] = None, target_id: Optional[str] = None,
                  detail: Optional[Any] = None, operator: Optional[str] = None,
                  ip: Optional[str] = None):
        try:
            entry = OperationLog(
                module=module, action=action, target_type=target_type,
                target_id=target_id, detail=detail, operator=operator or "system", ip=ip,
            )
            self.db.add(entry)
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Operation log failed (non-blocking): {e}")
            try:
                await self.db.rollback()
            except Exception as e:
                logger.debug(f"operation log rollback skipped (non-critical): {e}")


def _build_service(db: AsyncSession) -> OperationLogService:
    return OperationLogService(db)


async def log_operation(db: AsyncSession, module: str, action: str,
                        target_type=None, target_id=None, detail=None,
                        operator=None, ip=None):
    """Module-level convenience helper."""
    svc = _build_service(db)
    await svc.log(module, action, target_type=target_type, target_id=target_id,
                  detail=detail, operator=operator, ip=ip)
