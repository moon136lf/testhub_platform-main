"""Whitescan API endpoints (prefix /whitescan). semgrep scan + AI fix + regression cases."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.code_scan_service import CodeScanService
from app.services.ai_fix_service import AIFixService
from app.services.scan_export_service import ScanExportService
from app.schemas.whitescan import (
    ScanTriggerRequest, ScanListResponse, IssueUpdateRequest,
)

router = APIRouter()


def get_scan_service(db: AsyncSession = Depends(get_db)) -> CodeScanService:
    return CodeScanService(db)


@router.post("/scan")
async def trigger_scan(req: ScanTriggerRequest,
                       svc: CodeScanService = Depends(get_scan_service)):
    scan = await svc.create_scan(req.project_id, req.repo_url, req.branch)
    # Celery async dispatch; test env may lack broker -> degrade to error note
    try:
        from app.tasks.code_scan_tasks import run_scan_task
        run_scan_task.delay(str(scan["id"]), req.project_id, req.repo_url, req.branch)
        dispatched = True
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"task broker unavailable: {e}")
    return {"code": 0, "data": {"scan_id": scan["id"], "status": scan["status"],
                                 "dispatched": dispatched}}


@router.get("/scans")
async def list_scans(project_id: str = Query(...), page: int = Query(1, ge=1),
                     page_size: int = Query(20, ge=1, le=100),
                     svc: CodeScanService = Depends(get_scan_service)):
    return {"code": 0, "data": await svc.list_scans(project_id, page, page_size)}


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: str, svc: CodeScanService = Depends(get_scan_service)):
    scan = await svc.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"code": 0, "data": scan}


@router.get("/scans/{scan_id}/issues")
async def list_issues(scan_id: str, severity: Optional[str] = Query(None),
                      status: Optional[str] = Query(None),
                      svc: CodeScanService = Depends(get_scan_service)):
    return {"code": 0, "data": await svc.list_issues(scan_id, severity, status)}


@router.patch("/issues/{issue_id}")
async def update_issue(issue_id: str, req: IssueUpdateRequest,
                       svc: CodeScanService = Depends(get_scan_service)):
    result = await svc.update_issue(issue_id, req.status, req.handled_by or "system")
    if not result:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"code": 0, "data": result}


@router.post("/issues/{issue_id}/ai-fix")
async def ai_fix(issue_id: str, project_id: str = Query(...),
                 svc: CodeScanService = Depends(get_scan_service),
                 db: AsyncSession = Depends(get_db)):
    from app.services.ai_gateway import AIGateway
    fixer = AIFixService(db, AIGateway())
    result = await fixer.generate_fix(issue_id, project_id=project_id)
    if not result:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"code": 0, "data": result}


@router.post("/scans/{scan_id}/generate-cases")
async def generate_cases(scan_id: str, project_id: str = Query(...),
                         svc: CodeScanService = Depends(get_scan_service),
                         db: AsyncSession = Depends(get_db)):
    """基于被测系统代码结构生成功能回归用例 (clone → 静态解析 → AI 批量 → 落库)."""
    import asyncio, os, subprocess, tempfile, shutil, re as _re
    scan = await svc.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="scan not found")
    repo_url, branch = scan["repo_url"], scan.get("branch") or "main"
    if not _re.match(r"^(https?://|git@|ssh://|file://)", repo_url):
        raise HTTPException(status_code=400, detail="invalid repo_url")
    repo_path = tempfile.mkdtemp(prefix="funccase_")
    try:
        # run clone in executor: sync subprocess.run must not block the event loop
        loop = asyncio.get_running_loop()
        clone = await loop.run_in_executor(None, lambda: subprocess.run(
            ["git", "clone", "--depth", "1", "-b", branch, "--", repo_url, repo_path],
            capture_output=True, text=True, timeout=240,
            env={**os.environ, "GIT_ALLOW_PROTOCOL": "https:http:ssh:file"}))
        if clone.returncode != 0:
            raise HTTPException(status_code=400, detail=f"git clone failed: {clone.stderr[:300]}")
        from app.services.functional_case_generator import FunctionalCaseGenerator
        from app.services.ai_gateway import AIGateway
        gen = FunctionalCaseGenerator(db=db, gateway=AIGateway())
        result = await gen.generate_from_repo(project_id, repo_path, source_id=scan_id)
        return {"code": 0, "data": result}
    finally:
        shutil.rmtree(repo_path, ignore_errors=True)


@router.get("/scans/{scan_id}/export")
async def export_scan(scan_id: str, format: str = Query("xlsx", pattern="^(xlsx|md)$"),
                      svc: CodeScanService = Depends(get_scan_service)):
    issues = await svc.list_issues(scan_id)
    exporter = ScanExportService()
    # RFC 5987: latin-1-unsafe chars go in filename*; ascii fallback in filename
    from urllib.parse import quote
    if format == "xlsx":
        data = exporter.export_buglist_xlsx(issues)
        filename = f"BUG清单-{scan_id[:8]}.xlsx"
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data = exporter.export_issues_markdown(issues).encode("utf-8")
        filename = f"BUG清单-{scan_id[:8]}.md"
        mime = "text/markdown"
    quoted = quote(filename)
    return Response(
        content=data, media_type=mime,
        headers={"Content-Disposition":
                 f"attachment; filename=\"buglist-{scan_id[:8]}{filename[-4:]}\"; "
                 f"filename*=UTF-8''{quoted}"},
    )
