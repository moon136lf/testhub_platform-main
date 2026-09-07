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
from app.services.browser_session_manager import BrowserSessionManager, _bridge
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
)
from app.tasks.element_tasks import MIN_LOCATOR_SCORE

router = APIRouter()

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
            "element_name": sem.get("aria_label"),
        })

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
            "element_name": sem.get("aria_label"),
        })

    imported = await ElementService.batch_import_elements(db, page_id, selected_elements)

    # import done: close the session
    await CaptureSessionService.delete(session_id)

    return CaptureImportResponse(
        page_id=str(page_id),
        page_name=(page.page_name or (request.page_name or "")),
        imported_count=len(imported),
        failed_count=0,
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

    headless = not request.need_login
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
    return {"code": 0, "data": {"state": state, "url": url,
                                "title": title, "screenshot_b64": screenshot_b64}}


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
async def capture_browser_page(sid: str):
    """抓当前页元素 → 复用 P3 staging（CaptureSessionService）追加批次。"""
    sess = _browser_sess_or_404(sid)
    page = browser_mgr.get_page(sid)
    if page is None:
        raise HTTPException(status_code=404, detail="Browser released — open session first")

    # Playwright 对象绑定在 bridge loop（Proactor），所有调用须投递过去
    raw_elements = await _bridge.run(scan_interactive_elements(page, include_text=True))
    elements = await _bridge.run(_verify_elements(page, raw_elements))

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
        raise HTTPException(status_code=404, detail="No element at the given point")
    return {"code": 0, "data": {"element": element}}


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
