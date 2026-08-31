"""Whitescan API endpoints (prefix /whitescan). semgrep scan + AI fix + regression cases."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.services.code_scan_service import CodeScanService
from app.services.ai_fix_service import AIFixService
from app.services.regression_case_generator import RegressionCaseGenerator
from app.services.scan_export_service import ScanExportService
from app.schemas.whitescan import (
    ScanTriggerRequest, ScanListResponse, IssueUpdateRequest,
)
from app.models.test_case import TestCase

from uuid import UUID

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
    from app.services.ai_gateway import AIGateway
    generator = RegressionCaseGenerator(AIGateway())
    issues = await svc.list_issues(scan_id)

    # inject real _case_exists + persistence
    async def case_exists(pid, issue_id):
        q = select(TestCase).where(TestCase.source_issue_id == UUID(issue_id),
                                   TestCase.is_deleted.is_(False))
        return (await db.execute(q)).scalar_one_or_none() is not None

    async def persist(case, issue):
        tc = TestCase(
            project_id=UUID(project_id),
            name=case["name"][:100],
            priority=case.get("priority", "P1"),
            case_type="functional",
            automation_status="pending",
            precondition=case.get("precondition"),
            steps=case["steps"],
            expected_result=case.get("expected_result", "")[:200],
            source_issue_id=UUID(issue["id"]),
        )
        db.add(tc)
        await db.commit()
        return tc

    generator._case_exists = case_exists

    # wrap generate_case to persist
    original = generator.generate_case

    async def gen_and_persist(issue, suggestion, project_id=None):
        case = await original(issue, suggestion, project_id=project_id)
        await persist(case, issue)
        return case

    generator.generate_case = gen_and_persist
    result = await generator.batch_generate(project_id, issues)
    return {"code": 0, "data": result}


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
