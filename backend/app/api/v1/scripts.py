"""Script conversion API endpoints (模块 #4).

端点清单：
- POST /convert   触发批量转脚本 (异步 Celery 任务 + SSE 文字直播)
- GET  /          脚本列表 (可选 project_id / case_id 过滤)
- GET  /{id}      脚本详情
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid

from app.core.database import get_db
from app.models.project import Project
from app.models.test_case import TestCase, ScriptAsset
from app.schemas.script import ConvertRequest
from app.tasks.script_tasks import convert_scripts_task

router = APIRouter()


@router.post("/convert")
async def convert_scripts(request: ConvertRequest, db: AsyncSession = Depends(get_db)):
    """触发批量转脚本 (异步, SSE 文字直播)。"""
    try:
        project_uuid = uuid.UUID(request.project_id)
        case_uuids = [uuid.UUID(c) for c in request.case_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    # 验证项目存在
    result = await db.execute(select(Project).where(Project.id == project_uuid))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # 校验用例已定稿 (is_finalized=True, is_deleted=False)
    result = await db.execute(
        select(TestCase).where(
            TestCase.id.in_(case_uuids),
            TestCase.is_finalized.is_(True),
            TestCase.is_deleted.is_(False),
        )
    )
    found = result.scalars().all()
    if not found:
        raise HTTPException(status_code=400, detail="没有已定稿的用例可选")

    session_id = str(uuid.uuid4())
    convert_scripts_task.delay(
        session_id=session_id,
        case_ids=request.case_ids,
        project_id=request.project_id,
        ai_optimize=request.ai_optimize,
    )
    return {
        "code": 0,
        "message": "Script conversion started",
        "data": {
            "session_id": session_id,
            "sse_url": f"/api/sse/stream/{session_id}",
        },
    }


@router.get("")
async def list_scripts(
    project_id: Optional[str] = None,
    case_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """脚本列表。"""
    stmt = select(ScriptAsset)
    try:
        if project_id:
            stmt = stmt.where(ScriptAsset.project_id == uuid.UUID(project_id))
        if case_id:
            stmt = stmt.where(ScriptAsset.case_id == uuid.UUID(case_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    stmt = stmt.order_by(ScriptAsset.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    scripts = result.scalars().all()
    return {"code": 0, "data": [s.to_dict() for s in scripts]}


@router.get("/{script_id}")
async def get_script(script_id: str, db: AsyncSession = Depends(get_db)):
    """脚本详情。"""
    try:
        sid = uuid.UUID(script_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    result = await db.execute(select(ScriptAsset).where(ScriptAsset.id == sid))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Script not found")
    return {"code": 0, "data": asset.to_dict()}
