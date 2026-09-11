"""Reports API endpoints (prefix /reports). Read-only over #5a execution tables."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.storage import storage_client
from app.models.execution import ExecutionRecord, ExecutionBug
from app.services.execution_query_service import ExecutionQueryService
from app.services.report_generator import ReportGenerator

router = APIRouter()


def get_query_service(db: AsyncSession = Depends(get_db)) -> ExecutionQueryService:
    return ExecutionQueryService(db)

def get_generator_service(db: AsyncSession = Depends(get_db)) -> ReportGenerator:
    return ReportGenerator(db)


@router.get("/records")
async def list_records(
    project_id: str = Query(...),
    exec_type: str = Query(None),
    days: int = Query(7, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    svc: ExecutionQueryService = Depends(get_query_service),
):
    result = await svc.list_records(project_id, exec_type=exec_type, days=days, page=page, page_size=page_size)
    return {"code": 0, "data": result}


@router.get("/records/{exec_id}")
async def get_record_detail(exec_id: str, svc: ExecutionQueryService = Depends(get_query_service)):
    result = await svc.get_detail(exec_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return {"code": 0, "data": result}


@router.get("/records/{exec_id}/details")
async def list_details(exec_id: str, status: str = Query("fail"),
                       svc: ExecutionQueryService = Depends(get_query_service)):
    items = await svc.list_details(exec_id, status=status)
    return {"code": 0, "data": items}


@router.delete("/records/by-id/{record_id}")
async def delete_record(record_id: str, db: AsyncSession = Depends(get_db)):
    """软删执行记录（阶段10）：is_deleted=True，列表不再展示。"""
    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    rec = await db.get(ExecutionRecord, rid)
    if not rec:
        raise HTTPException(status_code=404, detail="记录不存在")
    rec.is_deleted = True
    await db.commit()
    return {"code": 0, "message": "记录已删除", "data": {"record_id": record_id}}


@router.get("/trend")
async def get_trend(project_id: str = Query(...), days: int = Query(7, ge=1, le=90),
                    svc: ExecutionQueryService = Depends(get_query_service)):
    items = await svc.get_trend(project_id, days=days)
    return {"code": 0, "data": items}


@router.post("/{exec_id}/generate")
async def generate_report(exec_id: str, force: bool = Query(False),
                          gen: ReportGenerator = Depends(get_generator_service)):
    result = await gen.generate_report(exec_id, force=force)
    if result is None:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return {"code": 0, "data": result}


@router.get("/{exec_id}/export")
async def export_report(exec_id: str, format: str = Query("html", pattern="^(html|pdf)$"),
                        svc: ExecutionQueryService = Depends(get_query_service)):
    detail = await svc.get_detail(exec_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Execution record not found")
    key = f"reports/{exec_id}.{format}"
    try:
        data = storage_client.get_object_bytes(key)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Report {format} not generated yet")
    mime = "text/html" if format == "html" else "application/pdf"
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": f"attachment; filename=report-{exec_id}.{format}"})


@router.get("/{exec_id}/bugs")
async def list_bugs(exec_id: str, db: AsyncSession = Depends(get_db)):
    """缺陷清单：该执行记录下自动生成的 bug 行。"""
    rec_q = select(ExecutionRecord).where(ExecutionRecord.exec_id == exec_id)
    rec = (await db.execute(rec_q)).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Execution record not found")
    q = (select(ExecutionBug).where(ExecutionBug.record_id == rec.id)
         .order_by(ExecutionBug.created_at))
    rows = (await db.execute(q)).scalars().all()
    return {"code": 0, "data": [b.to_dict() for b in rows]}
