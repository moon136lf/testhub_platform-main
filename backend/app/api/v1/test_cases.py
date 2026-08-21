"""
Test Case API endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.services.test_case_service import get_test_case_service, TestCaseService
from app.schemas.test_case import (
    CaseCreateRequest,
    CaseUpdateRequest,
    CaseFilterParams,
    BatchOperationRequest,
    CaseDetailResponse,
    CaseListResponse,
    CaseStatsResponse,
    CASE_TYPES,
    AUTOMATION_STATUSES,
    HALLUCINATION_STATUSES,
    _pattern,
)

router = APIRouter()


@router.get("/", response_model=CaseListResponse)
async def list_test_cases(
    project_id: str = Query(..., description="Project ID (required)"),
    point_id: Optional[str] = Query(None, description="Filter by test point ID"),
    priority: Optional[str] = Query(None, pattern="^(P0|P1|P2|P3)$", description="Priority level"),
    case_type: Optional[str] = Query(None, pattern=_pattern(CASE_TYPES)),
    automation_status: Optional[str] = Query(None, pattern=_pattern(AUTOMATION_STATUSES)),
    is_finalized: Optional[bool] = Query(None, description="Finalized status"),
    hallucination_status: Optional[str] = Query(None, pattern=_pattern(HALLUCINATION_STATUSES)),
    keyword: Optional[str] = Query(None, max_length=100, description="Search keyword"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    """
    List test cases with filtering and pagination
    """
    try:
        filters = CaseFilterParams(
            project_id=project_id,
            point_id=point_id,
            priority=priority,
            case_type=case_type,
            automation_status=automation_status,
            is_finalized=is_finalized,
            hallucination_status=hallucination_status,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )

        service = get_test_case_service(db)
        return await service.list_cases(filters)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/stats", response_model=CaseStatsResponse)
async def get_test_case_stats(
    project_id: str = Query(..., description="Project ID (required)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get statistics for test cases in a project
    """
    try:
        service = get_test_case_service(db)
        return await service.get_stats(project_id)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{case_id}", response_model=CaseDetailResponse)
async def get_test_case_detail(
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed information for a single test case
    """
    try:
        service = get_test_case_service(db)
        case = await service.get_case_detail(case_id)

        if not case:
            raise HTTPException(status_code=404, detail=f"Test case {case_id} not found")

        return case

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/", response_model=CaseDetailResponse, status_code=201)
async def create_test_case(
    request: CaseCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new test case
    """
    try:
        service = get_test_case_service(db)
        return await service.create_case(request)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/{case_id}", response_model=CaseDetailResponse)
async def update_test_case(
    case_id: str,
    request: CaseUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing test case
    """
    try:
        service = get_test_case_service(db)
        case = await service.update_case(case_id, request)

        if not case:
            raise HTTPException(status_code=404, detail=f"Test case {case_id} not found")

        return case

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/{case_id}", status_code=204)
async def delete_test_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a test case (soft delete)
    """
    try:
        service = get_test_case_service(db)
        success = await service.delete_case(case_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Test case {case_id} not found")

        return None

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch")
async def batch_operation_test_cases(
    request: BatchOperationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Perform batch operations on multiple test cases
    """
    try:
        service = get_test_case_service(db)
        result = await service.batch_operation(request)

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
