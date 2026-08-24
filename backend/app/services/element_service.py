"""
Element Service - Business Logic
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.element import PageRepository, ElementRepository
from typing import List, Dict
import uuid
import logging

logger = logging.getLogger(__name__)


class ElementService:
    """元素管理服务"""

    @staticmethod
    async def create_page(
        db: AsyncSession,
        project_id: uuid.UUID,
        page_name: str,
        page_url: str,
        screenshot_url: str
    ) -> PageRepository:
        """
        创建页面记录

        Args:
            db: 数据库会话
            project_id: 项目 ID
            page_name: 页面名称
            page_url: 页面 URL
            screenshot_url: 截图 URL

        Returns:
            创建的页面对象
        """
        try:
            page = PageRepository(
                project_id=project_id,
                page_name=page_name,
                page_url=page_url,
                screenshot_url=screenshot_url,
                element_count=0
            )
            db.add(page)
            await db.commit()
            await db.refresh(page)
            logger.info(f"Created page: {page_name} ({page.id})")
            return page
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to create page: {e}")
            raise

    @staticmethod
    async def get_page_by_url(
        db: AsyncSession,
        project_id: uuid.UUID,
        page_url: str
    ) -> PageRepository:
        """根据 URL 路径查询页面"""
        result = await db.execute(
            select(PageRepository).where(
                PageRepository.project_id == project_id,
                PageRepository.page_url == page_url
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def batch_import_elements(
        db: AsyncSession,
        page_id: uuid.UUID,
        elements: List[Dict]
    ) -> List[ElementRepository]:
        """
        批量导入元素

        Args:
            db: 数据库会话
            page_id: 页面 ID
            elements: 元素数据列表（来自 Playwright 抓取，字段：
                      type, id, class, name, placeholder, value, href,
                      coords {x,y,width,height}, text, locator_chain {strategies: [...]})

        Returns:
            导入的元素对象列表
        """
        try:
            # 获取页面所属 project_id（新模型要求 element_repository.project_id NOT NULL）
            result = await db.execute(
                select(PageRepository).where(PageRepository.id == page_id)
            )
            page = result.scalar_one_or_none()
            if page is None:
                raise ValueError(f"Page {page_id} not found")
            project_id = page.project_id

            element_objects: List[ElementRepository] = []

            for elem_data in elements:
                # 生成元素唯一标识（element_id）
                element_id = ElementService._generate_element_id(elem_data)

                # 归一化文本
                text = (elem_data.get("text") or "").strip()
                element_text = text[:200] if text else None

                # 定位策略链：Playwright 已产出 {"strategies": [...]}，缺失时兜底
                locator_chain = elem_data.get("locator_chain") or {"strategies": []}
                if isinstance(locator_chain, dict) and "strategies" in locator_chain:
                    locator_strategies = locator_chain
                elif isinstance(locator_chain, list):
                    locator_strategies = {"strategies": locator_chain}
                else:
                    locator_strategies = {"strategies": []}

                # 坐标
                coords = elem_data.get("coords") or {}
                position_x = int(coords["x"]) if coords.get("x") is not None else None
                position_y = int(coords["y"]) if coords.get("y") is not None else None
                width = int(coords["width"]) if coords.get("width") is not None else None
                height = int(coords["height"]) if coords.get("height") is not None else None

                # HTML 属性（过滤空值，便于后续自愈/校验）
                attributes = {
                    k: v for k, v in {
                        "id": elem_data.get("id"),
                        "class": elem_data.get("class"),
                        "name": elem_data.get("name"),
                        "placeholder": elem_data.get("placeholder"),
                        "value": elem_data.get("value"),
                        "href": elem_data.get("href"),
                    }.items() if v
                } or None

                # 语义信息（供自愈兜底使用）
                semantic_info = {
                    "type": elem_data.get("type"),
                    "text": element_text,
                    "placeholder": elem_data.get("placeholder"),
                    "coords": {
                        "x": position_x or 0,
                        "y": position_y or 0,
                        "width": width or 0,
                        "height": height or 0,
                    },
                }

                element = ElementRepository(
                    page_id=page_id,
                    project_id=project_id,
                    element_id=element_id,
                    element_name=element_text or element_id,
                    element_type=elem_data.get("type", "other"),
                    element_text=element_text,
                    locator_strategies=locator_strategies,
                    semantic_info=semantic_info,
                    position_x=position_x,
                    position_y=position_y,
                    width=width,
                    height=height,
                    attributes=attributes,
                    status="active",
                    confidence=0,
                    source="auto",
                    created_by="system",
                )
                db.add(element)
                element_objects.append(element)

            await db.commit()

            # 更新页面元素计数
            page.element_count = len(element_objects)
            page.last_fetch_at = func.now()
            await db.commit()

            logger.info(f"Imported {len(element_objects)} elements to page {page_id}")
            return element_objects

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to import elements: {e}")
            raise

    @staticmethod
    def _generate_element_id(elem_data: Dict) -> str:
        """
        生成元素唯一标识 (element_id)

        优先级: id > name > text > type+placeholder > type+uuid
        """
        # 1. 使用 id
        if elem_data.get("id"):
            return str(elem_data["id"])[:100]

        # 2. 使用 name
        if elem_data.get("name"):
            return str(elem_data["name"])[:100]

        # 3. 使用 text
        if elem_data.get("text") and len(str(elem_data["text"])) > 0:
            return str(elem_data["text"])[:100]

        # 4. 使用 type + placeholder
        if elem_data.get("placeholder"):
            return f"{elem_data.get('type', 'elem')}_{str(elem_data['placeholder'])[:80]}"

        # 5. 兜底: type + uuid
        return f"{elem_data.get('type', 'elem')}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    async def get_page_elements(
        db: AsyncSession,
        page_id: uuid.UUID
    ) -> List[ElementRepository]:
        """获取页面所有元素"""
        result = await db.execute(
            select(ElementRepository).where(
                ElementRepository.page_id == page_id,
                ElementRepository.status == "active"
            ).order_by(ElementRepository.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def delete_element(
        db: AsyncSession,
        element_id: uuid.UUID
    ):
        """删除元素（软删除）"""
        result = await db.execute(
            select(ElementRepository).where(ElementRepository.id == element_id)
        )
        element = result.scalar_one_or_none()
        if element:
            element.status = "deleted"
            await db.commit()
            logger.info(f"Deleted element: {element_id}")
