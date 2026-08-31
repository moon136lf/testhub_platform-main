"""Script conversion API endpoints (模块 #4).

端点清单：
- POST /convert   触发批量转脚本 (异步 Celery 任务 + SSE 文字直播)
- GET  /          脚本列表 (可选 project_id / case_id 过滤)
- GET  /{id}      脚本详情
- PUT  /{id}/confirm    TRANS-02 用户确认入库 (status->confirmed)
- POST /{id}/diagnose   调试修复 (四分类归因 + 失败步骤重生成)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid

from app.core.database import get_db
from app.models.project import Project
from app.models.test_case import TestCase, ScriptAsset
from app.schemas.script import (
    ConvertRequest, DiagnoseRequest,
    RunRequest, BatchRunRequest, QuickRunRequest,
)
from app.services.script_diagnose_service import ScriptDiagnoseService
from app.services.ai_gateway import AIGateway
from app.tasks.script_tasks import convert_scripts_task, run_scripts_task

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
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """脚本列表 (SCRIPT-02: 分类筛选 + 名称搜索)."""
    stmt = select(ScriptAsset)
    try:
        if project_id:
            stmt = stmt.where(ScriptAsset.project_id == uuid.UUID(project_id))
        if case_id:
            stmt = stmt.where(ScriptAsset.case_id == uuid.UUID(case_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    if category:
        stmt = stmt.where(ScriptAsset.category == category)
    if keyword:
        stmt = stmt.where(ScriptAsset.name.ilike(f"%{keyword}%"))
    stmt = stmt.order_by(ScriptAsset.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    scripts = result.scalars().all()
    return {"code": 0, "data": [s.to_dict() for s in scripts]}


@router.get("/stats")
async def get_script_stats(project_id: str, db: AsyncSession = Depends(get_db)):
    """统计卡片: total/passed/failed/never_run/pass_rate (实时聚合, SCRIPT 统计)."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    result = await db.execute(
        select(ScriptAsset).where(ScriptAsset.project_id == pid)
    )
    scripts = result.scalars().all()
    total = len(scripts)
    passed = sum(1 for s in scripts if s.last_status == "passed")
    failed = sum(1 for s in scripts if s.last_status == "failed")
    never_run = sum(1 for s in scripts if (s.run_count or 0) == 0)
    pass_rate = round((passed / total * 100), 2) if total else 0
    return {"code": 0, "data": {
        "total": total, "passed": passed, "failed": failed,
        "never_run": never_run, "pass_rate": pass_rate,
    }}


@router.post("/run")
async def run_script(request: RunRequest, db: AsyncSession = Depends(get_db)):
    """SCRIPT-03: 执行单个脚本, SSE 文字直播, 回写 script_asset."""
    try:
        sid = uuid.UUID(request.script_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    result = await db.execute(select(ScriptAsset).where(ScriptAsset.id == sid))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Script not found")
    session_id = str(uuid.uuid4())
    run_scripts_task.delay(
        session_id=session_id, script_id=request.script_id,
        config=request.config.model_dump(),
    )
    return {"code": 0, "message": "Execution started",
            "data": {"session_id": session_id, "exec_id": f"exec-{session_id[:8]}",
                     "sse_url": f"/api/sse/stream/{session_id}"}}


@router.post("/batch-run")
async def batch_run_scripts(request: BatchRunRequest, db: AsyncSession = Depends(get_db)):
    """SCRIPT-04: 批量执行, 汇总一条 execution_record."""
    # 校验 script_ids 存在性 (至少一个有效)
    try:
        sids = [uuid.UUID(s) for s in request.script_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID in script_ids")
    result = await db.execute(select(ScriptAsset).where(ScriptAsset.id.in_(sids)))
    found = result.scalars().all()
    if not found:
        raise HTTPException(status_code=400, detail="script_ids 中无有效脚本")
    session_id = str(uuid.uuid4())
    run_scripts_task.delay(
        session_id=session_id, script_ids=request.script_ids,
        config=request.config.model_dump(),
    )
    return {"code": 0, "message": "Batch execution started",
            "data": {"session_id": session_id, "exec_id": f"exec-{session_id[:8]}",
                     "sse_url": f"/api/sse/stream/{session_id}"}}


@router.post("/quick-run")
async def quick_run_script(request: QuickRunRequest, db: AsyncSession = Depends(get_db)):
    """SCRIPT-05: 快速运行粘贴脚本, 不入库, 写 execution_record(exec_type=quick_run)."""
    session_id = str(uuid.uuid4())
    run_scripts_task.delay(
        session_id=session_id, script_content=request.script_content,
        target_url=request.target_url, headless=request.headless,
    )
    return {"code": 0, "message": "Quick run started",
            "data": {"session_id": session_id, "sse_url": f"/api/sse/stream/{session_id}"}}


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


@router.put("/{script_id}/confirm")
async def confirm_script(script_id: str, db: AsyncSession = Depends(get_db)):
    """TRANS-02 用户确认入库: ScriptAsset.status->confirmed。"""
    try:
        sid = uuid.UUID(script_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    result = await db.execute(select(ScriptAsset).where(ScriptAsset.id == sid))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Script not found")
    asset.status = "confirmed"
    # #8: TRANS-02 确认入库 → 触发回归识别 (spec 偏差 H; 异常隔离不阻塞 confirm)
    try:
        from app.services.regression_service import RegressionService
        await RegressionService(db).identify_for_script(str(asset.project_id), script_id)
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"regression identify hook failed (non-blocking): {e}")
    await db.commit()
    return {"code": 0, "message": "Script confirmed",
            "data": {"script_id": script_id, "status": "confirmed"}}


@router.post("/{script_id}/diagnose")
async def diagnose_script(script_id: str, request: DiagnoseRequest,
                          db: AsyncSession = Depends(get_db)):
    """调试修复: 四分类归因 + 失败步骤重生成。"""
    try:
        sid = uuid.UUID(script_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    result = await db.execute(select(ScriptAsset).where(ScriptAsset.id == sid))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Script not found")

    svc = ScriptDiagnoseService(gateway=AIGateway())
    card = await svc.diagnose(
        error_type=request.error_type, error_msg=request.error_msg,
        script_fragment=request.script_fragment, failed_step=request.failed_step,
        screenshot_url=request.screenshot_url, dom_snapshot=request.dom_snapshot,
    )
    revised_script = None
    if card.get("can_fix") and card.get("revised_step"):
        revised_script = (asset.content or "") + "\n# --- 修复步骤 {} ---\n".format(
            request.failed_step) + card["revised_step"]
        asset.content = revised_script
        asset.append_diagnosis(card, mode="rule")  # #5c: 数组化, 保留历史
        asset.version = (asset.version or 1) + 1
        await db.commit()
    return {"code": 0, "data": {"diagnosis_card": card, "revised_script": revised_script}}
