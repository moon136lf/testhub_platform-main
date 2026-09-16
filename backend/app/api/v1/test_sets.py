"""测试集端点（阶段2）：执行规划层 CRUD。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.test_set_service import TestSetService
from app.services.execution_query_service import ExecutionQueryService

router = APIRouter()


class TestSetCreateRequest(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    case_ids: List[str] = Field(..., min_length=1)
    source: str = Field("manual", pattern="^(manual|ai_suggest|convert_page|ai_regression|manual_regression)$")
    description: Optional[str] = Field(None, max_length=500)


class TestSetUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class TestSetCasesRequest(BaseModel):
    case_ids: List[str] = Field(..., min_length=1)


@router.get("/test-sets")
async def list_test_sets(
    project_id: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    name: str = Query("", max_length=100),
    db: AsyncSession = Depends(get_db),
):
    """测试集列表（分页+名称模糊过滤）。"""
    sets, total = await TestSetService(db).list_sets(
        project_id, page=page, page_size=page_size, name=name)
    return {"code": 0, "data": [s.to_dict() for s in sets], "total": total}


@router.post("/test-sets")
async def create_test_set(request: TestSetCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        ts = await TestSetService(db).create_set(
            request.project_id, request.name, request.case_ids,
            source=request.source, description=request.description or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": ts.to_dict()}


@router.put("/test-sets/{set_id}")
async def update_test_set(set_id: str, request: TestSetUpdateRequest,
                          db: AsyncSession = Depends(get_db)):
    try:
        ts = await TestSetService(db).update_set(set_id, request.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": ts.to_dict()}


@router.delete("/test-sets/{set_id}")
async def delete_test_set(set_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await TestSetService(db).delete_set(set_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "deleted"}


@router.post("/test-sets/{set_id}/cases")
async def add_test_set_cases(set_id: str, request: TestSetCasesRequest,
                             db: AsyncSession = Depends(get_db)):
    try:
        await TestSetService(db).add_cases(set_id, request.case_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "added"}


@router.delete("/test-sets/{set_id}/cases/{case_id}")
async def remove_test_set_case(set_id: str, case_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await TestSetService(db).remove_case(set_id, case_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "removed"}


class TestSetRunRequest(BaseModel):
    headless: bool = True
    fail_fast: bool = False
    timeout: int = Field(60, ge=10, le=600)


@router.post("/test-sets/{set_id}/run")
async def run_test_set(set_id: str, request: TestSetRunRequest,
                       db: AsyncSession = Depends(get_db)):
    """执行测试集（无头/失败策略/超时可配）。"""
    try:
        result = await TestSetService(db).run_set(
            set_id, headless=request.headless,
            fail_fast=request.fail_fast, timeout=request.timeout)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": result}


@router.get("/test-sets/{set_id}")
async def get_test_set(set_id: str, db: AsyncSession = Depends(get_db)):
    """测试集单查（详情页用）。"""
    try:
        ts = await TestSetService(db).get_set(set_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if ts is None:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return {"code": 0, "data": ts.to_dict()}


@router.get("/test-sets/{set_id}/records")
async def list_test_set_records(set_id: str, page: int = Query(1, ge=1),
                                page_size: int = Query(20, ge=1, le=100),
                                result: str = Query("all", pattern="^(all|success|failed)$"),
                                db: AsyncSession = Depends(get_db)):
    """测试集执行记录（result: all/success/failed）。"""
    try:
        data = await ExecutionQueryService(db).list_set_records(
            set_id, page=page, page_size=page_size, result=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": data}


@router.get("/test-sets/{set_id}/trend")
async def test_set_trend(set_id: str, limit: int = Query(10, ge=1, le=50),
                         db: AsyncSession = Depends(get_db)):
    """测试集最近执行趋势。"""
    try:
        data = await ExecutionQueryService(db).set_trend(set_id, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": data}


@router.get("/test-sets/{set_id}/report")
async def test_set_report(set_id: str, db: AsyncSession = Depends(get_db)):
    """测试集报告（含失败截图 URL）。"""
    try:
        report = await TestSetService(db).get_report(set_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if report is None:
        return {"code": 0, "data": None}
    # 顺带同步执行结果到测试集（幂等）
    await TestSetService(db).sync_result_from_execution(set_id)
    return {"code": 0, "data": report}
