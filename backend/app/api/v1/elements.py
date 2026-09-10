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
- --- P3 会话式抓取工作台 ---
- POST /capture/sessions              创建抓取会话
- GET  /capture/sessions/{sid}        会话状态（工作台全量渲染数据）
- DELETE /capture/sessions/{sid}      丢弃会话
- POST /capture/sessions/{sid}/batches    追加抓取批次
- POST /capture/sessions/{sid}/elements/included   单元素勾选/取消
- POST /capture/sessions/{sid}/elements/included-all 全选/全不选
- DELETE /capture/sessions/{sid}/elements         删除单元素（body 带 temp_id）
- DELETE /capture/sessions/{sid}/batches          删除整批次（body 带 batch_idx）
- POST /capture/sessions/{sid}/import  按勾选入库
- POST /change-detection/{id}/fix     一键更新定位器 (ELEM-07)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
import uuid
import logging

from app.core.database import get_db
from app.schemas.element_schema import (
    ElementFetchRequest,
    ElementFetchResponse,
    ElementImportRequest,
    ElementImportResponse,
    PageResponse,
    ElementResponse,
    FetchHistoryResponse,
    CaptureSessionCreateRequest,
    CaptureSessionCreateResponse,
    CaptureBatchAddRequest,
    CaptureBatchAddResponse,
    CaptureElementOpRequest,
    CaptureAllOpRequest,
    CaptureElementDeleteRequest,
    CaptureBatchDeleteRequest,
    CaptureStateResponse,
    CaptureImportRequest,
    CaptureImportResponse,
)
from app.services.capture_session_service import CaptureSessionService
from app.services.browser_session_manager import BrowserSessionManager, _bridge, _call
from app.tasks.element_tasks import fetch_elements_task
from app.services.element_service import ElementService
from app.services.change_detection_service import ChangeDetectionService
from app.models.element import PageRepository, ElementRepository, FetchHistory, ChangeDetection
from app.schemas.element_schema import (
    BrowserOpenRequest,
    BrowserPickRequest,
)
from app.services.playwright_locator_core import (
    scan_interactive_elements,
    generate_locators_for_element,
    verify_and_score_locator,
    extract_semantic_info,
    _pick_element_via_dom,
    _node_locators_via_css,
    _NODE_CHAIN_JS,
)
from app.schemas.element_schema import NodeHighlightRequest
from app.tasks.element_tasks import MIN_LOCATOR_SCORE

router = APIRouter()

# 阶段1 元素资产管理端点：挂 asset_router（include 时无前缀，避免 /elements/elements-asset 双重前缀）
asset_router = APIRouter()
logger = logging.getLogger(__name__)

# P3.5 会话浏览器管理器（模块级单例；lifespan 挂 app.state 复用同一实例）
browser_mgr = BrowserSessionManager()


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
        include_text=request.include_text,
        exclude_menu=request.exclude_menu,
        max_list_rows=request.max_list_rows,
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

        # 规范化 URL 查重（尾斜杠差异视为同页），存在则复用，避免同页多行
        normalized = (request.page_url or "").rstrip("/")
        existing = None
        if normalized:
            all_pages = (await db.execute(
                select(PageRepository).where(
                    PageRepository.project_id == project_uuid)
            )).scalars().all()
            for p in all_pages:
                if (p.page_url or "").rstrip("/") == normalized:
                    existing = p
                    break
        if existing is not None:
            page = existing
            if request.page_name:
                page.page_name = request.page_name
            if request.screenshot_url:
                page.screenshot_url = request.screenshot_url
            page.last_fetch_at = func.now()
            await db.commit()
            await db.refresh(page)
        else:
            page = await ElementService.create_page(
                db,
                project_id=project_uuid,
                page_name=request.page_name,
                page_url=request.page_url,
                screenshot_url=request.screenshot_url,
            )
        page_id = page.id

    # 过滤用户勾选的元素（按 temp_id）
    # 注意: request.elements_data 已被 pydantic 解析为 ElementData 对象 (非 dict)，
    # 必须用属性访问；再转成 batch_import_elements 期望的 dict 契约
    # (type/text/coords/locator_chain —— 与 _persist_fetch_result 的映射一致)
    selected_elements = []
    for elem in request.elements_data:
        if elem.temp_id not in request.selected_element_ids:
            continue
        d = elem.model_dump()
        sem = d.get("semantic_info") or {}
        coords = sem.get("coords") or {
            "x": d.get("position_x"), "y": d.get("position_y"),
            "width": d.get("width"), "height": d.get("height")}
        attrs = d.get("attributes") or {}
        selected_elements.append({
            "temp_id": d.get("temp_id"),
            "type": d.get("element_type") or sem.get("type") or "other",
            "text": d.get("element_text") or sem.get("text") or "",
            "coords": coords,
            "locator_chain": d.get("locator_strategies") or {"strategies": []},
            "id": attrs.get("id"),
            "class": attrs.get("class"),
            "name": attrs.get("name"),
            "placeholder": attrs.get("placeholder"),
            "value": attrs.get("value"),
            "href": attrs.get("href"),
            # 用户在列表/弹窗编辑过的别名优先（element_name 是 d 的顶层键）
            "element_name": d.get("element_name") or sem.get("aria_label"),
        })

    if not selected_elements:
        raise HTTPException(status_code=400, detail="No elements selected")

    # 批量导入
    imported, skipped = await ElementService.batch_import_elements(
        db, page_id, selected_elements
    )

    return ElementImportResponse(
        page_id=str(page_id),
        page_name=imported[0].element_name if imported else "",
        imported_count=len(imported),
        failed_count=skipped,
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


@router.get("/pages/tree")
async def get_page_tree(
    project_id: str = Query(..., description="项目 ID"),
    db: AsyncSession = Depends(get_db),
):
    """页面树（按 parent_id 组装，根=parent_id IS NULL，按 last_fetch_at 倒序）"""
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

    nodes = {}
    for p in pages:
        d = p.to_dict()
        d["children"] = []
        nodes[p.id] = d

    roots = []
    for p in pages:
        d = nodes[p.id]
        parent = nodes.get(p.parent_id) if p.parent_id else None
        if parent is not None and parent is not d:
            parent["children"].append(d)
        else:
            roots.append(d)
    return {"code": 0, "message": "ok", "data": roots}


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


# ---------------- P3 capture workbench ----------------

@router.post("/capture/sessions", response_model=CaptureSessionCreateResponse)
async def create_capture_session(request: CaptureSessionCreateRequest):
    try:
        uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    state = await CaptureSessionService.create(request.project_id)
    return CaptureSessionCreateResponse(
        session_id=state["session_id"], project_id=state["project_id"]
    )

async def _load_session_or_404(session_id: str) -> dict:
    state = await CaptureSessionService.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Capture session not found or expired")
    return state

@router.get("/capture/sessions/{session_id}", response_model=CaptureStateResponse)
async def get_capture_state(session_id: str):
    state = await _load_session_or_404(session_id)
    elements = list(state.get("elements", {}).values())
    return CaptureStateResponse(
        session_id=session_id,
        project_id=state["project_id"],
        created_at=state.get("created_at"),
        batches=state.get("batches", []),
        elements=elements,
        total_elements=len(elements),
        included_count=sum(1 for e in elements if e.get("included")),
    )

@router.delete("/capture/sessions/{session_id}")
async def discard_capture_session(session_id: str):
    if not await CaptureSessionService.delete(session_id):
        raise HTTPException(status_code=404, detail="Capture session not found or expired")
    return {"discarded": True}

@router.post("/capture/sessions/{session_id}/batches", response_model=CaptureBatchAddResponse)
async def add_capture_batch(session_id: str, request: CaptureBatchAddRequest):
    elements = []
    for elem in request.elements:
        d = elem.model_dump()
        sem = d.get("semantic_info") or {}
        coords = sem.get("coords") or {
            "x": d.get("position_x"), "y": d.get("position_y"),
            "width": d.get("width"), "height": d.get("height"),
        }
        elements.append({
            "temp_id": d.get("temp_id"),
            "element_type": d.get("element_type") or sem.get("type") or "other",
            "element_text": d.get("element_text") or sem.get("text") or "",
            "locator_strategies": d.get("locator_strategies") or {"strategies": []},
            "semantic_info": sem,
            "position_x": coords.get("x"),
            "position_y": coords.get("y"),
            "width": coords.get("width"),
            "height": coords.get("height"),
            "attributes": d.get("attributes"),
        })
    try:
        result = await CaptureSessionService.add_batch(
            session_id, request.url, request.screenshot_url or "", elements
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Capture session not found or expired")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CaptureBatchAddResponse(**result)

@router.post("/capture/sessions/{session_id}/elements/included")
async def set_element_included(session_id: str, request: CaptureElementOpRequest):
    if not await CaptureSessionService.set_element_included(
        session_id, request.temp_id, request.included
    ):
        raise HTTPException(status_code=404, detail="Element not found in session")
    return {"temp_id": request.temp_id, "included": request.included}

@router.post("/capture/sessions/{session_id}/elements/included-all")
async def set_all_included(session_id: str, request: CaptureAllOpRequest):
    count = await CaptureSessionService.set_all_included(session_id, request.included)
    return {"included": request.included, "count": count}

@router.delete("/capture/sessions/{session_id}/elements")
async def delete_capture_element(session_id: str, request: CaptureElementDeleteRequest):
    if not await CaptureSessionService.delete_element(session_id, request.temp_id):
        raise HTTPException(status_code=404, detail="Element not found in session")
    return {"deleted": request.temp_id}

@router.delete("/capture/sessions/{session_id}/batches")
async def delete_capture_batch(session_id: str, request: CaptureBatchDeleteRequest):
    removed = await CaptureSessionService.remove_batch(session_id, request.batch_idx)
    if removed == 0:
        state = await _load_session_or_404(session_id)
        b = state.get("batches", [])
        if request.batch_idx >= len(b) or b[request.batch_idx].get("removed"):
            raise HTTPException(status_code=404, detail="Batch not found in session")
    return {"removed_elements": removed}

@router.post("/capture/sessions/{session_id}/import", response_model=CaptureImportResponse)
async def import_from_capture_session(
    session_id: str,
    request: CaptureImportRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.models.project import Project

    try:
        project_uuid = uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(select(Project).where(Project.id == project_uuid))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    selected = await CaptureSessionService.get_selected_elements(session_id)
    if selected is None:
        raise HTTPException(status_code=404, detail="Capture session not found or expired")
    if not selected["elements"]:
        raise HTTPException(status_code=400, detail="No elements selected in session")

    batches = (await CaptureSessionService.get(session_id) or {}).get("batches", [])
    last_screenshot = ""
    for b in reversed(batches):
        if b.get("screenshot_url") and not b.get("removed"):
            last_screenshot = b["screenshot_url"]
            break
    screenshot_url = request.screenshot_url or last_screenshot

    if request.page_id:
        try:
            page_id = uuid.UUID(request.page_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid page ID format")
    else:
        page_name = request.page_name
        page_url = request.page_url
        if not page_url and batches:
            page_url = next(
                (b["url"] for b in reversed(batches) if b.get("url") and not b.get("removed")),
                None,
            )
        if not page_name:
            page_name = page_url or "unnamed page"
        if not page_url:
            raise HTTPException(status_code=400, detail="page_url required (no batches to infer)")
        page = await ElementService.create_page(
            db, project_id=project_uuid, page_name=page_name,
            page_url=page_url, screenshot_url=screenshot_url,
        )
        page_id = page.id

    selected_elements = []
    for e in selected["elements"]:
        sem = e.get("semantic_info") or {}
        coords = sem.get("coords") or {
            "x": e.get("position_x"), "y": e.get("position_y"),
            "width": e.get("width"), "height": e.get("height"),
        }
        attrs = e.get("attributes") or {}
        selected_elements.append({
            "temp_id": e.get("temp_id"),
            "type": e.get("element_type") or sem.get("type") or "other",
            "text": e.get("element_text") or sem.get("text") or "",
            "coords": coords,
            "locator_chain": e.get("locator_strategies") or {"strategies": []},
            "id": attrs.get("id"),
            "class": attrs.get("class"),
            "name": attrs.get("name"),
            "placeholder": attrs.get("placeholder"),
            "value": attrs.get("value"),
            "href": attrs.get("href"),
            "element_name": e.get("element_name") or sem.get("aria_label"),
        })

    imported, skipped = await ElementService.batch_import_elements(db, page_id, selected_elements)

    # import done: close the session
    await CaptureSessionService.delete(session_id)

    return CaptureImportResponse(
        page_id=str(page_id),
        page_name=(page.page_name or (request.page_name or "")),
        imported_count=len(imported),
        failed_count=skipped,
        session_total=0,
    )


# ---------------- P3.5 会话浏览器（headed 人工登录 + 点选补抓） ----------------

_LOGIN_URL_HINTS = ("login", "signin", "sign-in", "auth", "sso")


@router.post("/capture/browser/open")
async def open_browser_session(request: BrowserOpenRequest):
    """打开（或复用）会话浏览器并导航到 url。need_login=True 时 headed 模式人工登录。"""
    try:
        uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    # 点选补抓坐标换算依赖真实窗口 —— headed 模式下 status 返回实际 innerWidth/innerHeight
    # 供前端动态换算；headless 固定 1920x1080 但与用户屏幕不一致时点选会偏。
    # 一律 headed：need_login=True 人工登录，False 时直接导航到目标页（不等待登录）。
    headless = False
    sid = await browser_mgr.open(
        request.project_id, request.url, headless=headless,
        need_login=request.need_login,
    )
    state = "awaiting_login" if request.need_login else "ready"
    sess = browser_mgr.get_session(sid)
    if sess is not None:
        sess.state = state
    return {"code": 0, "data": {"session_id": sid, "state": state}}


def _browser_sess_or_404(sid: str):
    sess = browser_mgr.get_session(sid)
    if sess is None:
        raise HTTPException(status_code=404, detail="Browser session not found")
    return sess


@router.get("/capture/browser/{sid}/status")
async def browser_session_status(sid: str):
    """会话状态 + 实时截图（base64）。awaiting_login 时按 URL 轻校验是否已离开登录页。"""
    sess = _browser_sess_or_404(sid)
    if sess.page is None:
        return {"code": 0, "data": {"state": "released", "url": None,
                                    "title": None, "screenshot_b64": None}}
    state = sess.state or "ready"
    url = sess.page.url
    if state == "awaiting_login":
        # 轻校验：URL 不含登录关键字视为登录完成
        if not any(h in (url or "").lower() for h in _LOGIN_URL_HINTS):
            state = "ready"
            sess.state = "ready"
    import base64
    title = await _bridge.run(sess.page.title())
    screenshot_b64 = base64.b64encode(await _bridge.run(sess.page.screenshot())).decode()
    # 实际视口尺寸（headed 模式跟随窗口，前端点选坐标换算需要）
    viewport = await _bridge.run(_call(
        sess.page.evaluate, "() => ({w: window.innerWidth, h: window.innerHeight})"))
    return {"code": 0, "data": {"state": state, "url": url,
                                "title": title, "screenshot_b64": screenshot_b64,
                                "viewport_width": viewport.get("w"),
                                "viewport_height": viewport.get("h")}}


async def _verify_elements(page, raw_elements) -> list:
    """定位器生成 → 验证评分 → 语义提取（与 element_tasks 阶段5 同流水线）。"""
    verified_elements = []
    for idx, elem in enumerate(raw_elements):
        candidates = await generate_locators_for_element(page, elem)
        verified_locators = []
        for candidate in candidates:
            verified = await verify_and_score_locator(page, candidate, elem)
            if verified and verified["score"] >= MIN_LOCATOR_SCORE:
                verified_locators.append(verified)
        if not verified_locators:
            continue
        semantic = await extract_semantic_info(page, elem)
        attributes = {
            "id": await elem.get_attribute("id"),
            "class": await elem.get_attribute("class"),
            "name": await elem.get_attribute("name"),
            "type": await elem.get_attribute("type"),
            "data-testid": await elem.get_attribute("data-testid"),
        }
        attributes = {k: v for k, v in attributes.items() if v} or None
        verified_locators_sorted = sorted(
            verified_locators, key=lambda x: x["score"], reverse=True
        )
        verified_elements.append({
            "temp_id": f"elem_{idx}_{uuid.uuid4().hex[:8]}",
            "element_type": semantic["type"],
            "element_text": semantic["text"],
            "locator_strategies": {"strategies": verified_locators_sorted},
            "semantic_info": semantic,
            "position_x": semantic["coords"]["x"],
            "position_y": semantic["coords"]["y"],
            "width": semantic["coords"]["width"],
            "height": semantic["coords"]["height"],
            "attributes": attributes,
        })
    return verified_elements


@router.post("/capture/browser/{sid}/capture")
async def capture_browser_page(
    sid: str,
    exclude_menu: bool = Query(False, description="排除左侧菜单栏元素"),
    max_list_rows: Optional[int] = Query(None, ge=1, le=50, description="表格单元格只保留最上 N 行"),
):
    """抓当前页元素 → 复用 P3 staging（CaptureSessionService）追加批次。"""
    sess = _browser_sess_or_404(sid)
    page = browser_mgr.get_page(sid)
    if page is None:
        raise HTTPException(status_code=404, detail="Browser released — open session first")

    # Playwright 对象绑定在 bridge loop（Proactor），所有调用须投递过去
    raw_elements = await _bridge.run(scan_interactive_elements(page, include_text=True))
    # 先验证提取为 dict（_apply_filters 消费 dict 形态的 position_x/element_type）
    elements = await _bridge.run(_verify_elements(page, raw_elements))
    from app.tasks.element_tasks import _apply_filters
    elements = _apply_filters(elements, text_filter="", type_filter="", debug_mode=False,
                              exclude_menu=exclude_menu, max_list_rows=max_list_rows,
                              viewport_width=1920)

    # 截图上传 MinIO → 批次截图 URL
    screenshot_url = ""
    try:
        png = await _bridge.run(page.screenshot())
        key = f"screenshots/{sess.project_id}/{uuid.uuid4().hex}.png"
        from app.core.storage import storage_client
        screenshot_url = await storage_client.upload_bytes(png, key)
    except Exception:
        screenshot_url = ""

    # staging 会话懒创建（复用 P3 redis staging）
    staging_id = getattr(sess, "staging_id", None)
    if staging_id:
        state = await CaptureSessionService.get(staging_id)
        if state is None:
            staging_id = None
    if not staging_id:
        created = await CaptureSessionService.create(sess.project_id)
        staging_id = created["session_id"]
        sess.staging_id = staging_id

    result = await CaptureSessionService.add_batch(staging_id, page.url, screenshot_url, elements)
    return {
        "code": 0,
        "data": {
            "elements": elements,
            "total_count": len(elements),
            "batch_idx": result["batch_idx"],
            "batch_count": result["batch_count"],
            "staging_session_id": staging_id,
        },
    }


@router.post("/capture/browser/{sid}/pick-element")
async def pick_browser_element(sid: str, request: BrowserPickRequest):
    """点选补抓：按坐标命中元素 → 定位卡片数据。"""
    _browser_sess_or_404(sid)
    page = browser_mgr.get_page(sid)
    if page is None:
        raise HTTPException(status_code=404, detail="Browser released — open session first")

    element = await _bridge.run(_pick_element_via_dom(page, request.x, request.y))
    if element is None:
        # 诊断信息帮助定位坐标偏差（视口/滚动/缩放）
        vp = await _bridge.run(_call(page.evaluate, "() => ({w: window.innerWidth, h: window.innerHeight, sy: window.scrollY, sx: window.scrollX})"))
        logger.warning(
            f"pick-element miss | sid={sid} x={request.x} y={request.y} "
            f"viewport={vp.get('w')}x{vp.get('h')} scroll=({vp.get('sx')},{vp.get('sy')})"
        )
        raise HTTPException(status_code=404, detail="No element at the given point")
    return {"code": 0, "data": {"element": element}}


@router.post("/capture/browser/{sid}/node-info")
async def node_info(sid: str, request: BrowserPickRequest):
    """点选坐标 → 打标记 → 返回祖先链（面包屑数据）。标记保留至下次 node-info/会话关闭。"""
    _browser_sess_or_404(sid)
    page = browser_mgr.get_page(sid)
    if page is None:
        raise HTTPException(status_code=404, detail="Browser released — open session first")

    chain = await _bridge.run(_call(page.evaluate, _NODE_CHAIN_JS, [request.x, request.y]))
    if chain is None:
        raise HTTPException(status_code=404, detail="No element at the given point")
    return {"code": 0, "data": {"chain": chain, "current_index": len(chain) - 1}}


@router.post("/capture/browser/{sid}/node-highlight")
async def node_highlight(sid: str, request: NodeHighlightRequest):
    """按 css_path 查节点 → 滚动到视口中央 + 橙色闪烁 2 秒。"""
    _browser_sess_or_404(sid)
    page = browser_mgr.get_page(sid)
    if page is None:
        raise HTTPException(status_code=404, detail="Browser released — open session first")

    found = await _bridge.run(_call(page.evaluate, """
(p) => {
  const el = document.querySelector(p);
  if (!el) return false;
  el.scrollIntoView({block: 'center'});
  el.style.outline = '3px solid #e6a23c';
  el.style.background = 'rgba(230,162,60,0.45)';
  setTimeout(() => { el.style.outline = ''; el.style.background = ''; }, 2000);
  return true;
}
""", [request.css_path]))
    return {"code": 0, "data": {"found": bool(found)}}


@router.post("/capture/browser/{sid}/node-locators")
async def node_locators(sid: str, request: NodeHighlightRequest):
    """按 css_path 对节点重跑定位器流水线 → 定位卡片数据 + 同级兄弟列表。"""
    _browser_sess_or_404(sid)
    page = browser_mgr.get_page(sid)
    if page is None:
        raise HTTPException(status_code=404, detail="Browser released — open session first")

    element = await _bridge.run(_node_locators_via_css(page, request.css_path))
    if element is None:
        raise HTTPException(status_code=404, detail="Node not found (page may have changed)")

    # 同级兄弟：在命中节点的 css_path 上取同父 children（排除自身）
    siblings = await _bridge.run(_call(page.evaluate, """
(p) => {
  const el = document.querySelector(p);
  if (!el || !el.parentElement) return [];
  return Array.from(el.parentElement.children)
    .filter(c => c !== el)
    .map(c => {
      const tag = c.tagName.toLowerCase();
      const parent = c.parentElement;
      let seg = tag;
      if (parent) {
        const same = Array.from(parent.children).filter(x => x.tagName === c.tagName);
        if (same.length > 1) seg += `:nth-of-type(${same.indexOf(c) + 1})`;
      }
      return {
        tag: tag,
        text: (c.innerText || '').trim().slice(0, 50) || null,
        css_path: p2css(c),
      };
    });

  function p2css(node) {
    let css = '';
    let cur = node;
    while (cur && cur.tagName) {
      const tag = cur.tagName.toLowerCase();
      let seg = tag;
      if (cur.id) { css = tag + '#' + cur.id + (css ? ' > ' + css : ''); break; }
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(x => x.tagName === cur.tagName);
        if (same.length > 1) seg += `:nth-of-type(${same.indexOf(cur) + 1})`;
      }
      css = css ? seg + ' > ' + css : seg;
      cur = parent;
      if (css.startsWith('html')) break;
    }
    return css;
  }
}
""", [request.css_path]))
    return {"code": 0, "data": {"element": element, "siblings": siblings or []}}


@router.post("/capture/browser/{sid}/release")
async def release_browser_session(sid: str):
    """释放页面：关浏览器保留会话数据（可再 open 复用）。"""
    _browser_sess_or_404(sid)
    await browser_mgr.release(sid)
    return {"code": 0, "data": {"released": True, "state": "released"}}


@router.post("/capture/browser/{sid}/close")
async def close_browser_session(sid: str):
    """关闭并删除整个会话。"""
    _browser_sess_or_404(sid)
    await browser_mgr.close_session(sid)
    return {"code": 0, "data": {"closed": True}}


# ---- 元素资产管理（阶段1） ----
from app.services.element_asset_service import ElementAssetService
from app.schemas.element_schema import LocatorVerifyRequest
from app.schemas.element_schema import (
    ElementUpdateRequest,
    LocatorReorderRequest,
    LocatorAddRequest,
    ElementAssetImportRequest,
)


def _element_uuid_or_400(element_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(element_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid element ID format")


@router.put("/elements/{element_id}")
async def update_element(element_id: str, request: ElementUpdateRequest,
                         db: AsyncSession = Depends(get_db)):
    """编辑元素（白名单字段）。"""
    try:
        el = await ElementAssetService(db).update_element(
            element_id, request.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": el.to_dict()}


@asset_router.post("/elements/{element_id}/locators/reorder")
async def reorder_locator(element_id: str, request: LocatorReorderRequest,
                          db: AsyncSession = Depends(get_db)):
    """定位器调序（上移/下移，score 跟随位置）。"""
    try:
        await ElementAssetService(db).reorder_locator(element_id, request.index, request.direction)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "reordered"}


@asset_router.post("/elements/{element_id}/locators")
async def add_locator(element_id: str, request: LocatorAddRequest,
                      db: AsyncSession = Depends(get_db)):
    """新增自定义定位器（手工来源）。"""
    try:
        await ElementAssetService(db).add_locator(element_id, request.type, request.value, request.score)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "added"}


@asset_router.get("/elements/{element_id}/references")
async def element_references(element_id: str, project_id: str = Query(...),
                             db: AsyncSession = Depends(get_db)):
    """元素引用计数 + 引用脚本清单（删除确认弹窗数据源）。"""
    el = await db.get(ElementRepository, _element_uuid_or_400(element_id))
    if not el:
        raise HTTPException(status_code=404, detail="元素不存在")
    svc = ElementAssetService(db)
    name = el.element_name or ""
    return {"code": 0, "data": {
        "count": await svc.count_references(project_id, name),
        "scripts": await svc.list_referring_scripts(project_id, name),
    }}


@asset_router.post("/elements/{element_id}/recycle")
async def recycle_element(element_id: str, db: AsyncSession = Depends(get_db)):
    """软删进回收站（引用确认由前端先调 references 端点）。"""
    try:
        await ElementAssetService(db).recycle_element(element_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "recycled"}


@asset_router.post("/elements/{element_id}/restore")
async def restore_element(element_id: str, db: AsyncSession = Depends(get_db)):
    """从回收站恢复。"""
    try:
        await ElementAssetService(db).restore_element(element_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "restored"}


@asset_router.get("/recycle-bin")
async def recycle_bin(project_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """回收站列表。"""
    els = await ElementAssetService(db).list_recycled(project_id)
    return {"code": 0, "data": [e.to_dict() for e in els]}


# ---------------- 页面树（层级 + 编辑 + 上下移 + 守护删除） ----------------
from app.schemas.element_schema import (
    SubPageCreateRequest,
    PageRenameRequest,
    PageMoveRequest,
    ElementCreateRequest,
)


@asset_router.post("/pages-tree")
async def create_sub_page(request: SubPageCreateRequest, db: AsyncSession = Depends(get_db)):
    """创建子页面（parent_id=None 即根级）。"""
    try:
        page = await ElementAssetService(db).create_sub_page(
            request.project_id, request.parent_id, request.page_name, request.page_url or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": page.to_dict()}


@asset_router.put("/pages-tree/{page_id}")
async def rename_page_node(page_id: str, request: PageRenameRequest, db: AsyncSession = Depends(get_db)):
    """重命名页面。"""
    try:
        await ElementAssetService(db).rename_page(page_id, request.page_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "renamed"}


@asset_router.post("/pages-tree/{page_id}/move")
async def move_page_node(page_id: str, request: PageMoveRequest, db: AsyncSession = Depends(get_db)):
    """同级上移/下移。"""
    try:
        await ElementAssetService(db).move_page(page_id, request.direction)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "moved"}


@asset_router.delete("/pages-tree/{page_id}")
async def delete_page_node(page_id: str, move_to_page_id: Optional[str] = Query(None),
                           force: bool = Query(False), db: AsyncSession = Depends(get_db)):
    """删页面（有子页面拒绝；有元素须给 move_to_page_id 或 force）。"""
    try:
        await ElementAssetService(db).delete_page(page_id, move_to_page_id, force)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "deleted"}


@asset_router.get("/elements-asset")
async def list_elements_asset(project_id: str = Query(...),
                              scope: Optional[str] = Query(None, pattern="^(page|global)$"),
                              page_id: Optional[str] = Query(None, description="页面ID或all"),
                              keyword: Optional[str] = Query(None, max_length=100),
                              page: Optional[int] = Query(None, ge=1,
                                  description="页码（传入即启用分页，返回分页信封；不传保持旧版平铺列表，向后兼容）"),
                              page_size: int = Query(10, ge=1, le=100),
                              db: AsyncSession = Depends(get_db)):
    """元素列表（管理页数据源）：scope/page/keyword 过滤，updated_at 倒序（NULL 最后）。

    向后兼容：不带 page 参数 → 返回旧版平铺列表 {"data": [dict,...]}（已附带 page_name）；
    带 page 参数 → 分页信封 {"data": {"items": [...], "total": N, "page": p, "page_size": s}}。
    """
    svc = ElementAssetService(db)
    try:
        if page is None:
            els = await svc.list_elements(project_id, scope, page_id, keyword=keyword)
            return {"code": 0, "data": await svc.attach_page_names(els)}
        rows, total = await svc.list_elements_paged(
            project_id, scope, page_id, keyword=keyword, page=page, page_size=page_size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": {
        "items": await svc.attach_page_names(rows),
        "total": total, "page": page, "page_size": page_size,
    }}


from pydantic import BaseModel, Field


class ElementStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(active|deprecated)$",
                        description="active=启用 deprecated=禁用")


@asset_router.put("/elements-asset/{element_id}/status")
async def set_element_status(element_id: str, request: ElementStatusRequest,
                             db: AsyncSession = Depends(get_db)):
    """启用/禁用元素（复用 status 字段：active/deprecated）。

    禁用后转脚本链路 find_by_name（仅匹配 active）自动排除该元素。"""
    try:
        el = await ElementAssetService(db).set_status(element_id, request.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": el.to_dict()}


@asset_router.post("/elements-asset")
async def create_element_asset(request: ElementCreateRequest, db: AsyncSession = Depends(get_db)):
    """新建元素（手工录入，支持全局作用域）。"""
    try:
        el = await ElementAssetService(db).create_element(
            request.project_id, request.name, request.element_type, request.element_text or "",
            scope=request.scope, page_id=request.page_id,
            locators=request.locators,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": el.to_dict()}


@asset_router.post("/elements/{element_id}/locators/verify")
async def verify_element_locator(element_id: str, request: LocatorVerifyRequest,
                                 db: AsyncSession = Depends(get_db)):
    """快速校验：用激活环境的 URL 开页面跑一次定位。
    复用 playwright_service 登录态链路。占位页面（/__placeholder__/）不可校验。"""
    uid = _element_uuid_or_400(element_id)
    el = await db.get(ElementRepository, uid)
    if not el:
        raise HTTPException(status_code=404, detail="元素不存在")
    if not el.page_id:
        raise HTTPException(status_code=400, detail="全局元素无页面URL，无法校验")
    page_row = await db.get(PageRepository, el.page_id)
    if not page_row:
        raise HTTPException(status_code=404, detail="所属页面不存在")
    if (page_row.page_url or "").startswith("/__placeholder__/"):
        raise HTTPException(status_code=400, detail="该页面为占位页面（无真实URL），请先在页面树中补全页面URL再校验")

    from app.models.system import TestEnv
    env = (await db.execute(
        select(TestEnv).where(TestEnv.status == "active").limit(1)
    )).scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=400, detail="无激活测试环境，请先在「环境管理」激活")

    from app.services.playwright_service import PlaywrightService
    from app.services.element_asset_service import verify_locator_on_page
    pw = PlaywrightService()
    page = None
    try:
        await pw.start(headless=True)
        target_url = env.url.rstrip("/") + (page_row.page_url or "")
        page = await pw.browser.new_page()
        await page.goto(target_url, timeout=30000, wait_until="networkidle")
        result = await verify_locator_on_page(
            page, {"type": request.locator_type, "value": request.locator_value,
                   "score": request.score or 0})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"页面打开失败: {str(e)[:200]}")
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
        await pw.close()
    return {"code": 0, "data": result}


@router.get("/elements-export")
async def export_elements(project_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    """导出项目全部 active 元素为 JSON（前端下载为文件）。"""
    data = await ElementAssetService(db).export_elements(project_id)
    return {"code": 0, "data": data}


@router.post("/elements-import")
async def import_elements_asset(request: ElementAssetImportRequest, db: AsyncSession = Depends(get_db)):
    """导入元素 JSON（跨项目/环境复用）。返回 imported/skipped/errors 摘要。"""
    try:
        result = await ElementAssetService(db).import_elements(request.project_id, request.payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": result}
