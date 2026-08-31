"""Reviews API endpoints (prefix /reviews). Project-level review orchestration."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.review_service import ReviewService
from app.schemas.review import (
    ReviewStatsResponse, BatchRefineRequest, BatchRefineResultItem,
    ProjectRefinementReportResponse, BatchReviewRequest, BatchReviewResponse,
)
from typing import List

router = APIRouter()


def get_review_service(db: AsyncSession = Depends(get_db)) -> ReviewService:
    return ReviewService(db)


@router.get("/stats", response_model=ReviewStatsResponse)
async def get_stats(project_id: str = Query(...),
                    svc: ReviewService = Depends(get_review_service)):
    return await svc.get_review_stats(project_id)


@router.post("/batch-refine", response_model=List[BatchRefineResultItem])
async def batch_refine(req: BatchRefineRequest,
                       svc: ReviewService = Depends(get_review_service)):
    return await svc.batch_refine(req.project_id, req.case_ids)


@router.get("/refinement-report", response_model=ProjectRefinementReportResponse)
async def get_refinement_report(project_id: str = Query(...),
                                svc: ReviewService = Depends(get_review_service)):
    return await svc.get_project_refinement_report(project_id)


@router.post("/batch-review", response_model=BatchReviewResponse)
async def batch_review(req: BatchReviewRequest,
                       svc: ReviewService = Depends(get_review_service)):
    return await svc.batch_update_review(req.project_id, req.case_ids,
                                         req.review_status, req.review_comment)
