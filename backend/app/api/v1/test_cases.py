"""
Test Case API endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID

from app.core.database import get_db
from app.models.case_batch import CaseBatch
from app.models.test_case import TestCase, TestPoint
from app.services.test_case_service import get_test_case_service, TestCaseService
from app.services.import_export_service import ImportExportService
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
from app.schemas.refinement import ApplySuggestionsRequest

router = APIRouter()


def _get_io_service(db: AsyncSession) -> ImportExportService:
    return ImportExportService(db)


@router.get("/export")
async def export_test_cases(
    project_id: str = Query(...),
    format: str = Query("json", pattern="^(xlsx|json|xmind)$"),
    db: AsyncSession = Depends(get_db),
):
    """Export test cases of a project to xlsx / json / xmind."""
    try:
        svc = _get_io_service(db)
        data = await svc.export_cases_async(project_id, format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    ext = {"xlsx": "xlsx", "json": "json", "xmind": "xmind"}[format]
    mime = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "json": "application/json",
        "xmind": "application/x-xmind",
    }[format]
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f"attachment; filename=test_cases.{ext}"},
    )


@router.post("/import")
async def import_test_cases(
    project_id: str = Query(...),
    format: str = Query("csv", pattern="^(xlsx|csv|md)$"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Import test cases from an uploaded xlsx / csv / md file."""
    try:
        file_bytes = await file.read()
        svc = _get_io_service(db)
        result = await svc.import_cases(project_id, file_bytes, format)
        return {"code": 0, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/batches")
async def list_case_batches(
    project_id: UUID = Query(...),
    batch_type: str | None = Query(None, pattern="^(whitescan_api|whitescan_ui|ai_generate|manual)$"),
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """生成记录列表（用例管理记录层）。"""
    try:
        q = select(CaseBatch).where(CaseBatch.project_id == project_id)
        if batch_type:
            q = q.where(CaseBatch.batch_type == batch_type)
        if keyword:
            q = q.where(CaseBatch.batch_name.ilike(f"%{keyword}%"))
        total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
        q = q.order_by(CaseBatch.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await db.execute(q)).scalars().all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    return {"code": 0, "data": {"items": [b.to_dict() for b in rows],
                                "total": total, "page": page, "page_size": page_size}}


@router.get("/batches/{batch_id}/cases")
async def list_batch_cases(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """批内用例列表（查看页数据源）。附测试点名称（point_name），供列表展示。"""
    try:
        r = await db.execute(
            select(TestCase, TestPoint.name)
            .outerjoin(TestPoint, TestCase.point_id == TestPoint.id)
            .where(TestCase.batch_id == batch_id,
                   TestCase.is_deleted.is_(False))
            .order_by(TestCase.created_at))
        rows = r.all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    data = []
    for case, point_name in rows:
        d = case.to_dict()
        d["point_name"] = point_name
        data.append(d)
    return {"code": 0, "data": data}


@router.delete("/batches/{batch_id}", status_code=204)
async def delete_case_batch(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    """删批次：软删批内全部用例 + 物理删批次行。"""
    try:
        batch = await db.get(CaseBatch, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="批次不存在")
        await db.execute(update(TestCase).where(TestCase.batch_id == batch_id)
                         .values(is_deleted=True))
        await db.delete(batch)
        await db.commit()  # 显式提交: 批次行物理删除需立即生效
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/", response_model=CaseListResponse)
async def list_test_cases(
    project_id: str = Query(..., description="Project ID (required)"),
    point_id: Optional[str] = Query(None, description="Filter by test point ID"),
    priority: Optional[str] = Query(None, pattern="^(P0|P1|P2|P3)$", description="Priority level"),
    case_type: Optional[str] = Query(None, pattern=_pattern(CASE_TYPES)),
    automation_status: Optional[str] = Query(None, pattern=_pattern(AUTOMATION_STATUSES)),
    is_finalized: Optional[bool] = Query(None, description="Finalized status"),
    hallucination_status: Optional[str] = Query(None, pattern=_pattern(HALLUCINATION_STATUSES)),
    source_type: Optional[str] = Query(None, pattern="^(ai_gen|whitescan|manual)$"),
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
            source_type=source_type,
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


@router.get("/{case_id}/versions")
async def list_case_versions(case_id: str, db: AsyncSession = Depends(get_db)):
    try:
        service = get_test_case_service(db)
        versions = await service.list_versions(case_id)
        return {"code": 0, "data": [v.to_dict() for v in versions]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{case_id}/versions/{version}")
async def get_case_version(case_id: str, version: int, db: AsyncSession = Depends(get_db)):
    try:
        service = get_test_case_service(db)
        v = await service.get_version(case_id, version)
        if not v:
            raise HTTPException(status_code=404, detail="Version not found")
        return {"code": 0, "data": v.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{case_id}/rollback")
async def rollback_case(case_id: str, version: int = Query(..., ge=1), db: AsyncSession = Depends(get_db)):
    try:
        service = get_test_case_service(db)
        result = await service.rollback_case(case_id, version)
        if not result:
            raise HTTPException(status_code=404, detail="Case not found")
        return {"code": 0, "data": result.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{case_id}/refine")
async def refine_case(case_id: str, db: AsyncSession = Depends(get_db)):
    """Trigger (synchronous) E2E refinement, persist the report + feasibility fields."""
    try:
        svc = get_test_case_service(db)
        report = await svc.refine_case(case_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return {"code": 0, "data": report}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{case_id}/refinement-report")
async def get_refinement_report(case_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch the latest persisted refinement report for a case."""
    try:
        svc = get_test_case_service(db)
        detail = await svc.get_case_detail(case_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Case not found")
        return {"code": 0, "data": getattr(detail, "refinement_report", None)}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/{case_id}/apply-suggestions")
async def apply_suggestions(
    case_id: str,
    body: ApplySuggestionsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Apply refinement suggestions (all or by id) and persist the updated steps."""
    try:
        svc = get_test_case_service(db)
        result = await svc.apply_suggestions(case_id, body.suggestion_ids)
        if not result:
            raise HTTPException(status_code=404, detail="Case or refinement report not found")
        return {"code": 0, "data": result.model_dump()}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.patch("/{case_id}/review")
async def update_review(
    case_id: str,
    request: CaseUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update review-only fields (status / comment / feasibility / reason).

    Other mutable fields are cleared so the underlying update_case cannot touch them.
    """
    # Neutralize non-review fields so only review fields can be set here.
    request.name = None
    request.steps = None
    request.priority = None
    request.case_type = None
    request.automation_status = None
    request.precondition = None
    request.expected_result = None
    request.is_finalized = None
    request.hallucination_status = None
    request.point_id = None

    try:
        svc = get_test_case_service(db)
        result = await svc.update_case(case_id, request)
        if not result:
            raise HTTPException(status_code=404, detail="Case not found")
        return {"code": 0, "data": result.model_dump()}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
