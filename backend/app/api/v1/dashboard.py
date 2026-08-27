"""Dashboard API endpoints (prefix /dashboard). Read-only 4-table aggregation."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.dashboard_service import DashboardService
from app.schemas.dashboard import OverviewResponse

router = APIRouter()


def get_dashboard_service(db: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(db)


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    project_id: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=90),
    svc: DashboardService = Depends(get_dashboard_service),
):
    result = await svc.get_overview(project_id, days=days)
    return result
