"""
Element Extraction Celery Tasks with SSE Progress Streaming (Task 13)

异步抓取元素任务，带 8 阶段 SSE 直播：
1. init (5%)        - 启动浏览器
2. navigate (15%)   - 访问页面
3. login (25%)      - 可选登录
4. scan (35%-45%)   - 扫描可交互元素
5. verify (45%-80%) - 为每个元素生成并验证定位器
6. screenshot (85%) - 保存截图
7. upload (90%)     - 上传截图到 MinIO
8. complete (100%)  - 完成，返回元素数据
"""

import asyncio
import uuid
import logging
from datetime import datetime
from typing import Optional

from app.tasks import celery_app
from app.services.playwright_service import PlaywrightService
from app.services.playwright_locator_core import (
    scan_interactive_elements,
    generate_locators_for_element,
    verify_and_score_locator,
    extract_semantic_info,
)
from app.services.element_cache_service import ElementCacheService
from app.core.storage import storage_client
from app.core.sse import SSEStream

logger = logging.getLogger(__name__)

# 定位器入库最低评分阈值（score < 60 的定位器丢弃）
MIN_LOCATOR_SCORE = 60


def _apply_filters(elements: list, text_filter: str, type_filter: str, debug_mode: bool) -> list:
    """扫描后过滤: debug_mode 直通; text_filter 任一词是 element_text 子串保留; type_filter 白名单."""
    if debug_mode:
        return elements
    out = elements
    if text_filter:
        words = [w.strip() for w in text_filter.split(",") if w.strip()]
        out = [e for e in out if e.get("element_text") and any(w in e["element_text"] for w in words)]
    if type_filter:
        types = {t.strip() for t in type_filter.split(",") if t.strip()}
        out = [e for e in out if e.get("element_type") in types]
    return out


@celery_app.task(bind=True, name="fetch_elements_task")
def fetch_elements_task(
    self,
    session_id: str,
    project_id: str,
    url: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    text_filter: Optional[str] = "",
    type_filter: Optional[str] = "",
    debug_mode: bool = False,
):
    """
    异步抓取元素任务（带 SSE 直播）

    Args:
        session_id: SSE 会话 ID
        project_id: 项目 ID
        url: 目标 URL
        username: 可选登录用户名
        password: 可选登录密码

    Returns:
        抓取结果字典 {session_id, url, screenshot_url, elements, total_count, duration_seconds}
    """
    return asyncio.run(_fetch_elements_async(
        session_id, project_id, url, username, password,
        text_filter, type_filter, debug_mode
    ))


async def _fetch_elements_async(
    session_id: str,
    project_id: str,
    url: str,
    username: Optional[str],
    password: Optional[str],
    text_filter: Optional[str] = "",
    type_filter: Optional[str] = "",
    debug_mode: bool = False,
):
    """实际的异步抓取逻辑"""
    sse = SSEStream(session_id)
    pw_service = PlaywrightService()
    start_time = datetime.now()
    context = None
    page = None

    try:
        # 阶段 1: 启动浏览器 (5%)
        await sse.send_message(
            type="system", stage="init",
            content="正在启动浏览器...",
            progress=0.05,
        )
        await pw_service.start()

        # 阶段 2: 访问页面 (15%)
        await sse.send_message(
            type="system", stage="navigate",
            content=f"正在访问 {url}...",
            progress=0.15,
        )
        context = await pw_service.browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(30000)
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # 阶段 3: 可选登录 (25%)
        if username and password:
            await sse.send_message(
                type="system", stage="login",
                content="检测到登录信息，尝试自动登录...",
                progress=0.25,
            )
            await pw_service._auto_login(page, username, password)
            await page.wait_for_timeout(2000)

        # 阶段 4: 扫描元素 (35%->45%)
        await sse.send_message(
            type="system", stage="scan",
            content="正在扫描页面元素...",
            progress=0.35,
        )
        raw_elements = await scan_interactive_elements(page)
        raw_elements = _apply_filters(raw_elements, text_filter, type_filter, debug_mode)

        await sse.send_message(
            type="system", stage="scan",
            content=f"发现 {len(raw_elements)} 个可交互元素，开始生成定位器...",
            progress=0.45,
        )

        # 阶段 5: 为每个元素生成并验证定位器 (45%->80%)
        verified_elements = []
        total = len(raw_elements)

        for idx, elem in enumerate(raw_elements):
            # 生成候选定位器
            candidates = await generate_locators_for_element(page, elem)

            # 验证并评分，只保留 score >= 60 的定位器
            verified_locators = []
            for candidate in candidates:
                verified = await verify_and_score_locator(page, candidate, elem)
                if verified and verified["score"] >= MIN_LOCATOR_SCORE:
                    verified_locators.append(verified)

            # 无有效定位器则跳过该元素
            if not verified_locators:
                continue

            # 提取语义信息
            semantic = await extract_semantic_info(page, elem)

            # 获取元素属性
            attributes = {
                "id": await elem.get_attribute("id"),
                "class": await elem.get_attribute("class"),
                "name": await elem.get_attribute("name"),
                "type": await elem.get_attribute("type"),
                "data-testid": await elem.get_attribute("data-testid"),
            }
            attributes = {k: v for k, v in attributes.items() if v} or None

            # 组装元素数据（按评分降序排列定位器）
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

            # 每 5 个元素或最后一个时推送进度
            progress = 0.45 + (idx + 1) / total * 0.35
            if (idx + 1) % 5 == 0 or idx == total - 1:
                await sse.send_message(
                    type="system", stage="verify",
                    content=f"已验证 {idx + 1}/{total} 个元素，有效元素 {len(verified_elements)} 个",
                    progress=progress,
                )

        # 阶段 6: 截图 (85%)
        await sse.send_message(
            type="system", stage="screenshot",
            content="正在保存页面截图...",
            progress=0.85,
        )
        screenshot_bytes = await page.screenshot(full_page=True)

        # 阶段 7: 上传截图 (90%)
        await sse.send_message(
            type="system", stage="upload",
            content="正在上传截图到存储服务...",
            progress=0.90,
        )
        screenshot_filename = f"screenshots/{project_id}/{uuid.uuid4()}.png"
        screenshot_url = await storage_client.upload_bytes(
            screenshot_bytes, screenshot_filename
        )

        # 计算耗时
        duration = (datetime.now() - start_time).total_seconds()

        # 阶段 8: 完成 (100%) - 元素落库 + 写入页面缓存（三类 Redis 键之一）
        # 抓取结果持久化: page_repository(upsert) + element_repository + fetch_history
        try:
            imported = await _persist_fetch_result(
                project_id, url, screenshot_url, verified_elements, bool(username and password))
            await sse.send_message(
                type="system", stage="complete",
                content=f"已入库 {imported} 个元素到元素库",
                progress=0.99,
            )
        except Exception as persist_err:
            logger.error(f"【元素库】结果入库失败 | project_id={project_id} url={url} 原因={persist_err} 建议=检查数据库连接")
            imported = 0

        try:
            await ElementCacheService.cache_page(project_id, url, {
                "url": url,
                "screenshot_url": screenshot_url,
                "element_count": len(verified_elements),
            })
        except Exception as cache_err:
            logger.warning(f"Page cache write failed (non-fatal): {cache_err}")

        await sse.send_message(
            type="success", stage="complete",
            content=f"抓取完成！共识别 {len(verified_elements)} 个有效元素，耗时 {duration:.1f}秒",
            progress=1.0,
            data={
                "elements": verified_elements,
                "screenshot_url": screenshot_url,
                "imported_count": imported,
                "total_count": len(verified_elements),
            },
        )

        logger.info(
            f"【元素库】抓取完成 | session={session_id} 元素={len(verified_elements)} 耗时={duration:.1f}s 入库={imported}"
        )

        return {
            "session_id": session_id,
            "url": url,
            "screenshot_url": screenshot_url,
            "elements": verified_elements,
            "total_count": len(verified_elements),
            "imported_count": imported,
            "duration_seconds": int(duration),
        }

    except Exception as e:
        error_msg = f"抓取失败: {str(e)}"
        logger.error(f"【元素库】抓取失败 | session={session_id} 原因={error_msg} 建议=检查目标URL可达性与浏览器环境", exc_info=True)

        await sse.send_message(
            type="error", stage="error",
            content=error_msg,
            progress=0,
        )
        raise

    finally:
        # 清理浏览器资源
        try:
            if page is not None:
                await page.close()
            if context is not None:
                await context.close()
        except Exception:
            pass
        await pw_service.close()


async def _persist_fetch_result(
    project_id: str,
    url: str,
    screenshot_url: str,
    elements: list,
    used_login: bool,
) -> int:
    """抓取结果落库: page_repository upsert + element_repository 批量导入 + fetch_history.

    返回入库元素数. 任务结果此前只写 redis 缓存 (有 TTL 即失), 元素库页面查不到 — 补此断链.
    """
    import uuid as _uuid

    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.models.element import ElementRepository, FetchHistory, PageRepository
    from app.services.element_service import ElementService

    # 注意: batch_import_elements 内部自行 commit, 因此这里不套 db.begin(),
    # 每步独立提交 (页面行先落, 元素随之, 历史最后)
    async with AsyncSessionLocal() as db:
        # 1. 页面 upsert (同 project+url 复用既有行)
        r = await db.execute(
            select(PageRepository).where(
                PageRepository.project_id == _uuid.UUID(project_id),
                PageRepository.page_url == url))
        page = r.scalar_one_or_none()
        if page is None:
            page = PageRepository(
                project_id=_uuid.UUID(project_id),
                page_name=url.rstrip("/").rsplit("/", 1)[-1] or "index",
                page_url=url,
            )
            db.add(page)
        page.screenshot_url = screenshot_url
        page.last_fetch_at = datetime.now()
        await db.commit()
        await db.refresh(page)

        # 2. 清掉该页旧元素 (重复抓取时以本次为准, 避免 unique 冲突), 再批量导入
        await db.execute(delete(ElementRepository).where(ElementRepository.page_id == page.id))
        await db.commit()

        # 抓取产物字段名 (element_type/element_text/locator_strategies/semantic_info)
        # 与 batch_import_elements 期望的 (type/text/coords/locator_chain) 不同 — 转换映射
        import_items = []
        for e in elements:
            sem = e.get("semantic_info") or {}
            coords = sem.get("coords") or {
                "x": e.get("position_x"), "y": e.get("position_y"),
                "width": e.get("width"), "height": e.get("height")}
            attrs = e.get("attributes") or {}
            import_items.append({
                "type": e.get("element_type") or sem.get("type") or "other",
                "text": e.get("element_text") or sem.get("text") or "",
                "coords": coords,
                "locator_chain": e.get("locator_strategies") or {"strategies": []},
                "id": attrs.get("id"),
                "class": attrs.get("class"),
                "name": attrs.get("name"),
                "placeholder": attrs.get("placeholder"),
            })
        imported_elems = await ElementService.batch_import_elements(db, page.id, import_items)

        # 3. 抓取历史
        db.add(FetchHistory(
            page_id=page.id,
            project_id=_uuid.UUID(project_id),
            elements_found=len(elements),
            elements_imported=len(imported_elems),
            screenshot_url=screenshot_url[:500],
            fetch_url=url[:500],
            used_login=used_login,
            status="success",
        ))
        await db.commit()
        imported = len(imported_elems)

    logger.info(f"Persisted fetch result | page_id={page.id} imported={imported}")
    return imported
