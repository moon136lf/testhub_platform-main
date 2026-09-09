"""回归测试 API (#8) — /regression 8 端点 (REG-01~05)."""
import logging
import uuid as uuid_mod

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.regression import (IdentifyRequest, MembersRequest,
                                    RegResponse, RunRequest)
from app.services.regression_service import RegressionService
from app.tasks.script_tasks import run_scripts_task

logger = logging.getLogger(__name__)
router = APIRouter()


def _pid(v: str) -> uuid_mod.UUID:
    try:
        return uuid_mod.UUID(v)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")


def _get_svc(db: AsyncSession = Depends(get_db)) -> RegressionService:
    return RegressionService(db)


@router.get("/list")
async def list_regression(project_id: str = Query(...),
                          category: str = Query(None),
                          keyword: str = Query(None),
                          svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """管理视图: 全量 confirmed 脚本 + 回归状态 (含未纳入行, REG-01/03)."""
    _pid(project_id)
    return RegResponse(data=await svc.list_view(project_id, category=category, keyword=keyword))


@router.post("/members")
async def set_members(request: MembersRequest,
                      svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """REG-03: 勾选批量加入/移出 (include_source=manual)."""
    _pid(request.project_id)
    for sid in request.script_ids:
        await svc.set_member(request.project_id, uuid_mod.UUID(sid), action=request.action)
    await svc.db.commit()
    return RegResponse(data={"updated": len(request.script_ids), "action": request.action})


@router.post("/identify")
async def identify(request: IdentifyRequest,
                   svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """REG-02: 手动重算全项目识别."""
    _pid(request.project_id)
    return RegResponse(data=await svc.identify_project(request.project_id))


@router.get("/stats")
async def stats(project_id: str = Query(...),
                svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """统计卡: included ⋈ last_status 聚合."""
    _pid(project_id)
    return RegResponse(data=await svc.get_stats(project_id))


@router.post("/run")
async def run_regression(request: RunRequest,
                         svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """REG-04: 对 included=true 全部脚本批量执行 (exec_type=ui_regression)."""
    _pid(request.project_id)
    items = await svc.list_view(request.project_id)
    script_ids = [it["script"]["id"] for it in items if it["included"]]
    if not script_ids:
        raise HTTPException(status_code=400, detail="回归集为空，无脚本可执行")
    session_id = str(uuid_mod.uuid4())
    run_scripts_task.delay(
        session_id=session_id, script_ids=script_ids,
        config=request.config.model_dump(),
        exec_type="ui_regression",
    )
    return RegResponse(data={"session_id": session_id,
                             "exec_id": f"exec-{session_id[:8]}",
                             "sse_url": f"/api/sse/stream/{session_id}",
                             "total": len(script_ids)})


@router.get("/latest-execution")
async def latest_execution(script_id: str = Query(...),
                           svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """行内 [报告]: 按 script_id 反查最近一次执行."""
    result = await svc.latest_execution(script_id)
    if result is None:
        raise HTTPException(status_code=404, detail="该脚本暂无执行记录")
    return RegResponse(data=result)


@router.post("/{exec_id}/push")
async def push_report(exec_id: str) -> RegResponse:
    """REG-05: 推送报告到已配置的 webhook（钉钉/企微/飞书/自定义，system_setting notify 类）。
    未配置任何渠道时返回 pushed=False，前端如实提示。"""
    from app.services.notifier import notify_report_ready
    result = await notify_report_ready(exec_id, {"source": "regression"})
    return RegResponse(data={"pushed": result["pushed"], "channels": result["channels"], "exec_id": exec_id})


@router.get("/report-summary")
async def report_summary(project_id: str = Query(...),
                         svc: RegressionService = Depends(_get_svc)) -> RegResponse:
    """内嵌报告块: 最近一次 ui_regression 执行摘要 + 失败 detail 行."""
    _pid(project_id)
    return RegResponse(data=await svc.report_summary(project_id))
