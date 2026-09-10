"""
Element Service - Business Logic
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy import func
from app.models.element import PageRepository, ElementRepository
from typing import List, Dict, Optional
import uuid
import re
import logging

logger = logging.getLogger(__name__)

# 别名默认生成的类型中文映射（P3 工作台：别名默认中文）
TYPE_CN = {
    "button": "按钮", "input": "输入框", "select": "下拉框", "link": "链接",
    "textarea": "文本域", "span": "文本", "p": "文本", "h1": "标题", "h2": "标题",
    "h3": "标题", "label": "标签", "td": "单元格", "th": "表头", "other": "元素",
}


def _default_cn_alias(elem_type: str, counter: int) -> str:
    """{类型中文}{序号}，如 按钮1 / 输入框2."""
    cn = TYPE_CN.get(elem_type or "other", TYPE_CN["other"])
    return f"{cn}{counter}"


class ElementService:
    """元素管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_by_name(self, project_id: str, element_name: str) -> Optional[ElementRepository]:
        """按项目+元素名/文本查找元素 (供转脚本定位匹配用, TRANS-01)。"""
        if not element_name:
            return None
        result = await self.db.execute(
            select(ElementRepository).where(
                ElementRepository.project_id == uuid.UUID(project_id),
                ElementRepository.status == "active",
                or_(
                    ElementRepository.element_name == element_name,
                    ElementRepository.element_text == element_name,
                ),
            )
        )
        return result.scalar_one_or_none()

    async def writeback_healed_locator(self, element_id: str, healed_locator: dict) -> bool:
        """TRANS-08: confidence>=3 自愈成功后回写 ElementRepository (source=healed)."""
        if not element_id or not healed_locator:
            return False
        result = await self.db.execute(
            select(ElementRepository).where(ElementRepository.element_id == element_id)
        )
        el = result.scalar_one_or_none()
        if not el:
            return False
        # healed_locator 可能是 dict 或 list, 统一为 strategies 数组
        if isinstance(healed_locator, dict):
            strategies = healed_locator.get("strategies") or [healed_locator]
        else:
            strategies = healed_locator
        el.locator_strategies = {"strategies": strategies}
        el.source = "healed"
        el.confidence = (el.confidence or 0) + 1
        await self.db.flush()
        return True

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
            # 别名中文默认序号：按类型计序（按钮1/按钮2/输入框1...）
            type_counters: Dict[str, int] = {}
            # 页内去重：同一批次可能含重复 element_id（如重复抓取同页、相同文本派生），
            # 唯一约束 uq_element_repository_page_element 会整体回滚，这里保留首个
            seen_element_ids: set = set()
            skipped_duplicates = 0

            # 库内已有 element_id（同页面先前抓取过）：命中则更新定位器而非新插入，
            # 否则唯一约束 uq_element_repository_page_element 整批回滚
            existing_result = await db.execute(
                select(ElementRepository.element_id).where(
                    ElementRepository.page_id == page_id)
            )
            existing_ids = {row[0] for row in existing_result.all()}

            for elem_data in elements:
                # 生成元素唯一标识（element_id）
                element_id = ElementService._generate_element_id(elem_data)
                if element_id in seen_element_ids:
                    skipped_duplicates += 1
                    logger.warning(
                        f"Skip duplicate element_id '{element_id}' in batch import to page {page_id}"
                    )
                    continue
                seen_element_ids.add(element_id)

                if element_id in existing_ids:
                    # 已存在：刷新定位策略链与坐标（重新抓取覆盖旧值），不重复插入
                    upd_result = await db.execute(
                        select(ElementRepository).where(
                            ElementRepository.page_id == page_id,
                            ElementRepository.element_id == element_id)
                    )
                    existing_el = upd_result.scalar_one_or_none()
                    if existing_el is not None:
                        coords0 = elem_data.get("coords") or {}
                        existing_el.position_x = int(coords0["x"]) if coords0.get("x") is not None else existing_el.position_x
                        existing_el.position_y = int(coords0["y"]) if coords0.get("y") is not None else existing_el.position_y
                        existing_el.width = int(coords0["width"]) if coords0.get("width") is not None else existing_el.width
                        existing_el.height = int(coords0["height"]) if coords0.get("height") is not None else existing_el.height
                        chain = elem_data.get("locator_chain") or {}
                        if isinstance(chain, dict) and chain.get("strategies"):
                            existing_el.locator_strategies = chain
                        elif isinstance(chain, list) and chain:
                            existing_el.locator_strategies = {"strategies": chain}
                        if existing_el.status == "recycled":
                            existing_el.status = "active"  # 重抓复活
                        skipped_duplicates += 1
                        logger.info(f"Refresh existing element '{element_id}' on page {page_id}")
                    continue

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
                    "context": {},  # Schema 字段；详细上下文仅抓取流水线产出
                    "coords": {
                        "x": position_x or 0,
                        "y": position_y or 0,
                        "width": width or 0,
                        "height": height or 0,
                    },
                }

                # 别名：用户指定 > element_text > {类型中文}{序号}
                elem_type = elem_data.get("type", "other") or "other"
                user_name = (elem_data.get("element_name") or "").strip()
                if user_name:
                    element_name = user_name[:100]
                elif element_text:
                    element_name = element_text
                else:
                    type_counters[elem_type] = type_counters.get(elem_type, 0) + 1
                    element_name = _default_cn_alias(elem_type, type_counters[elem_type])

                element = ElementRepository(
                    page_id=page_id,
                    project_id=project_id,
                    element_id=element_id,
                    element_name=element_name,
                    element_type=elem_type,
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
            page.element_count = (page.element_count or 0) + len(element_objects)
            page.last_fetch_at = func.now()
            await db.commit()

            logger.info(
                f"Imported {len(element_objects)} elements to page {page_id} "
                f"(skipped {skipped_duplicates} duplicates)"
            )
            return element_objects, skipped_duplicates

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to import elements: {e}")
            raise

    @staticmethod
    def _generate_element_id(elem_data: Dict) -> str:
        """
        生成元素唯一标识 (element_id)

        优先级: id > name > text(+坐标) > text > type+placeholder(+坐标) > type+uuid
        同属性重复元素（如表格每行的相同按钮、多个相同 placeholder 的输入框）
        通过追加坐标后缀区分，避免被页内去重误杀。
        """
        coords = elem_data.get("coords") or {}
        coord_suffix = ""
        if coords.get("x") is not None and coords.get("y") is not None:
            coord_suffix = f"_{int(coords['x'])}_{int(coords['y'])}"

        # 1. 使用 id + 坐标（同 id 属性的元素位置不同仍需区分）
        if elem_data.get("id"):
            return f"{str(elem_data['id'])[:80]}{coord_suffix}"[:100]

        # 2. 使用 name + 坐标
        if elem_data.get("name"):
            return f"{str(elem_data['name'])[:80]}{coord_suffix}"[:100]

        # 3. 使用 text + 坐标
        if elem_data.get("text") and len(str(elem_data["text"])) > 0:
            return f"{str(elem_data['text'])[:80]}{coord_suffix}"[:100]

        # 4. 使用 type + placeholder + 坐标
        if elem_data.get("placeholder"):
            return f"{elem_data.get('type', 'elem')}_{str(elem_data['placeholder'])[:60]}{coord_suffix}"[:100]

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


class ElementLocatorLookup:
    """ElementRepository -> pipeline ElementLookupProto 适配器。
    locator_strategies JSONB -> Playwright 定位器字符串。"""

    def __init__(self, element_service: ElementService):
        self._svc = element_service

    async def find(self, project_id: str, target: str) -> Optional[str]:
        el = await self._svc.find_by_name(project_id, target)
        if not el:
            return None
        strategies = el.locator_strategies or []
        if isinstance(strategies, dict):
            strategies = strategies.get("strategies", [])
        norm = normalize_strategies(strategies)
        for s in norm:
            loc = strategy_to_playwright(s)
            if loc:
                return loc
        return None


# ---- 定位器选择（阶段1 统一置信度方案）----
# 旧方案：硬编码类型优先级 role>text>label>placeholder>css —— 已废除。
# 新方案：score 说话（抓取端已按 base_score+验证加减分排序），类型只作为缺 score 时的归一化基准。

_TYPE_BASELINE = {
    "id": 100, "data-testid": 95, "name": 90, "role-text": 85,
    "text": 80, "class-type": 70, "css": 70, "xpath": 55,
}


def normalize_strategies(strategies: list) -> list:
    """归一化定位策略列表：补齐缺失的 score/unique/verified，按 score 降序。

    旧数据（score 缺失）按类型基准分补齐；调序端点直接改 score，排序以 score 为准。"""
    out = []
    for s in strategies or []:
        if not isinstance(s, dict) or not s.get("value"):
            continue
        s = dict(s)
        if not isinstance(s.get("score"), (int, float)):
            s["score"] = _TYPE_BASELINE.get(s.get("type"), 30)
        s.setdefault("unique", False)
        s.setdefault("verified", False)
        out.append(s)
    return sorted(out, key=lambda x: x["score"], reverse=True)


def select_primary_locator(strategies: list) -> Optional[str]:
    """取 score 最高的定位值（消费端唯一决策：score 说话，不看类型）。"""
    norm = normalize_strategies(strategies)
    return norm[0]["value"] if norm else None


def build_fallback_chain(strategies: list) -> list:
    """首选之外的定位值列表（降序），供脚本生成 fallback。"""
    norm = normalize_strategies(strategies)
    return [s["value"] for s in norm[1:]]


def strategy_to_playwright(s: dict) -> Optional[str]:
    """单条策略 -> Playwright 定位器表达式。类型词表对齐生成端（playwright_locator_core）。"""
    t, v = s.get("type", ""), s.get("value", "")
    if not v:
        return None
    if t in ("id", "css", "class-type"):
        return f'page.locator("{v}")'
    if t == "data-testid":
        return f"page.locator({v})"
    if t == "name":
        return f"page.locator({v})"
    if t == "text":
        return f'page.get_by_text("{v}")'
    if t == "role-text":
        # value 形如 "button[role='button']:has-text('提交')" → get_by_role(role, name=text)
        m = re.match(r"^(\w+)\[role='([\w-]+)'\]:has-text\('(.+)'\)$", v)
        if m:
            return f'page.get_by_role("{m.group(2)}", name="{m.group(3)}")'
        return None
    if t == "xpath":
        return f'page.locator("xpath={v}")'
    # label/placeholder 等无生成端产出的类型：无可靠映射，交给 fallback
    return None
