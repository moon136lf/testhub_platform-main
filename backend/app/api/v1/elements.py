"""
Element API endpoints - 元素库管理接口 (Task 15 重构)

端点清单：
- POST /fetch                        触发异步元素抓取（Celery + SSE）
- POST /import                        批量导入元素到库
- GET  /pages                        获取项目的所有页面
- GET  /pages/{page_id}/elements     获取页面的所有元素
- GET  /pages/{page_id}/history      获取页面的抓取历史
- DELETE /elements/{element_id}       删除元素（软删除）
- POST /change-detection              触发变更检测 (ELEM-05)
- POST /change-detection/{id}/fix     一键更新定位器 (ELEM-07)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import uuid

from app.core.database import get_db
from app.schemas.element_schema import (
    ElementFetchRequest,
    ElementFetchResponse,
    ElementImportRequest,
    ElementImportResponse,
    PageResponse,
    ElementResponse,
    FetchHistoryResponse,
)
from app.tasks.element_tasks import fetch_elements_task
from app.services.element_service import ElementService
from app.services.change_detection_service import ChangeDetectionService
from app.models.element import PageRepository, ElementRepository, FetchHistory, ChangeDetection

router = APIRouter()


@router.get("/screenshot")
async def get_screenshot(key: str = Query(..., description="MinIO object key, e.g. screenshots/{project_id}/{uuid}.png")):
    """截图代理端点: 前端 <img> 走 /api/v1/elements/screenshot?key=...,
    由后端从 MinIO 拉取 (bucket 非公开, 直连 MinIO URL 会 AccessDenied)."""
    from app.core.storage import storage_client
    if not key.startswith("screenshots/") or ".." in key:
        raise HTTPException(status_code=400, detail="Invalid screenshot key")
    try:
        import asyncio
        data = await asyncio.get_running_loop().run_in_executor(
            None, lambda: storage_client.get_object_bytes(key))
    except Exception:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return Response(content=data, media_type="image/png")


@router.post("/fetch", response_model=ElementFetchResponse)
async def fetch_elements(
    request: ElementFetchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    触发异步元素抓取任务

    返回 session_id 和 sse_url，客户端通过 SSE 实时获取抓取进度。
    """
    try:
        project_uuid = uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    # 验证项目是否存在
    from app.models.project import Project

    result = await db.execute(
        select(Project).where(Project.id == project_uuid)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 生成 session_id 并提交 Celery 任务
    session_id = f"fetch_{uuid.uuid4().hex[:12]}"
    task = fetch_elements_task.delay(
        session_id=session_id,
        project_id=request.project_id,
        url=request.url,
        username=request.username,
        password=request.password,
        text_filter=request.text_filter,
        type_filter=request.type_filter,
        debug_mode=request.debug_mode,
    )

    return ElementFetchResponse(
        session_id=session_id,
        sse_url=f"/api/v1/sse/element-fetch/{session_id}",
    )


@router.post("/import", response_model=ElementImportResponse)
async def import_elements(
    request: ElementImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    批量导入元素到库

    支持两种模式：
    - 提供已有 page_id
    - 提供新建页面信息（page_name + page_url）
    """
    try:
        project_uuid = uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    # 创建或获取页面
    if request.page_id:
        try:
            page_id = uuid.UUID(request.page_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid page ID format")
    else:
        if not request.page_name or not request.page_url:
            raise HTTPException(
                status_code=400,
                detail="page_name and page_url are required when page_id is not provided",
            )

        page = await ElementService.create_page(
            db,
            project_id=project_uuid,
            page_name=request.page_name,
            page_url=request.page_url,
            screenshot_url=request.screenshot_url,
        )
        page_id = page.id

    # 过滤用户勾选的元素（按 temp_id）
    selected_elements = [
        elem for elem in request.elements_data
        if elem.get("temp_id") in request.selected_element_ids
    ]

    if not selected_elements:
        raise HTTPException(status_code=400, detail="No elements selected")

    # 批量导入
    imported = await ElementService.batch_import_elements(
        db, page_id, selected_elements
    )

    return ElementImportResponse(
        page_id=str(page_id),
        page_name=imported[0].element_name if imported else "",
        imported_count=len(imported),
        failed_count=0,
    )


@router.get("/pages", response_model=List[PageResponse])
async def list_pages(
    project_id: str = Query(..., description="项目 ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取项目的所有页面列表"""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(
        select(PageRepository)
        .where(PageRepository.project_id == project_uuid)
        .order_by(PageRepository.last_fetch_at.desc().nullslast())
    )
    pages = result.scalars().all()

    return [PageResponse(**page.to_dict()) for page in pages]


@router.get("/pages/{page_id}/elements", response_model=List[ElementResponse])
async def get_page_elements(
    page_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取页面的所有 active 元素"""
    try:
        page_uuid = uuid.UUID(page_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid page ID format")

    result = await db.execute(
        select(ElementRepository).where(
            ElementRepository.page_id == page_uuid,
            ElementRepository.status == "active",
        ).order_by(ElementRepository.created_at)
    )
    elements = result.scalars().all()

    return [ElementResponse(**elem.to_dict()) for elem in elements]


@router.get("/pages/{page_id}/history", response_model=List[FetchHistoryResponse])
async def get_fetch_history(
    page_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取页面的抓取历史（最近 10 条）"""
    try:
        page_uuid = uuid.UUID(page_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid page ID format")

    result = await db.execute(
        select(FetchHistory)
        .where(FetchHistory.page_id == page_uuid)
        .order_by(FetchHistory.fetch_time.desc())
        .limit(10)
    )
    histories = result.scalars().all()

    return [FetchHistoryResponse(**h.to_dict()) for h in histories]


@router.delete("/elements/{element_id}")
async def delete_element(
    element_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除元素（软删除，status -> deleted）"""
    try:
        element_uuid = uuid.UUID(element_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid element ID format")

    result = await db.execute(
        select(ElementRepository).where(ElementRepository.id == element_uuid)
    )
    element = result.scalar_one_or_none()

    if not element:
        raise HTTPException(status_code=404, detail="Element not found")

    element.status = "deleted"
    await db.commit()

    return {"message": "Element deleted successfully"}


# ============================================================
# 变更检测端点 (ELEM-05/06/07)
# ============================================================


@router.get("/login-state")
async def get_login_state(project_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """登录态摘要 (P1 占位: login_state 表 P3 才建, 无表/无行时返回 not_configured)."""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    try:
        from sqlalchemy import text
        r = await db.execute(
            text("SELECT cookie_count, localstorage_count, status, obtained_at "
                 "FROM login_state WHERE project_id = :pid AND env = 'default' LIMIT 1"),
            {"pid": str(project_uuid)})
        row = r.first()
    except Exception:
        row = None  # 表不存在 (P1 无迁移)
    if row is None:
        return {"code": 0, "data": {"status": "not_configured", "cookie_count": 0,
                                    "localstorage_count": 0, "obtained_at": None}}
    return {"code": 0, "data": {"status": row.status, "cookie_count": row.cookie_count,
                                "localstorage_count": row.localstorage_count,
                                "obtained_at": row.obtained_at.isoformat() if row.obtained_at else None}}


@router.post("/change-detection")
async def trigger_change_detection(
    page_id: str = Query(..., description="页面 ID"),
    db: AsyncSession = Depends(get_db),
):
    """ELEM-05: 触发变更检测，对比两次抓取的元素差异"""
    try:
        page_uuid = uuid.UUID(page_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid page ID format")

    try:
        detection = await ChangeDetectionService.detect_changes(db, page_uuid)
        return {
            "code": 0,
            "message": "Change detection completed",
            "data": detection.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/change-detection/{detection_id}/fix")
async def fix_change_detection(
    detection_id: str,
    db: AsyncSession = Depends(get_db),
):
    """ELEM-07: 一键更新受影响元素的定位器"""
    try:
        detection_uuid = uuid.UUID(detection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid detection ID format")

    try:
        result = await ChangeDetectionService.update_locators_one_click(db, detection_uuid)
        return {
            "code": 0,
            "message": "Locators updated successfully",
            "data": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
