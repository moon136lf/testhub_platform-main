"""
Change Detection Service - 变更检测服务 (ELEM-05/06/07)

ELEM-05: 对比两次抓取，检测 added/removed/modified 元素
ELEM-06: 标记变更影响的脚本
ELEM-07: 一键更新受影响元素的定位器
"""

import logging
from typing import Dict, List, Optional, Any
from uuid import UUID
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.element import (
    PageRepository,
    ElementRepository,
    FetchHistory,
    ChangeDetection,
)

logger = logging.getLogger(__name__)


class ChangeDetectionService:
    """变更检测服务"""

    @staticmethod
    def _element_signature(elem: Dict[str, Any]) -> str:
        """
        生成元素签名用于匹配（element_id 优先，否则用 element_text+coords）
        """
        if elem.get("element_id"):
            return str(elem["element_id"])
        # 退化匹配：文本+坐标
        text = elem.get("element_text") or elem.get("text") or ""
        coords = elem.get("semantic_info", {}).get("coords", {}) if isinstance(elem.get("semantic_info"), dict) else {}
        x = coords.get("x", elem.get("position_x", 0))
        y = coords.get("y", elem.get("position_y", 0))
        return f"{text}|{x}|{y}"

    @staticmethod
    def _locator_summary(elem: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """提取元素定位器摘要（用于变更记录）"""
        strategies = elem.get("locator_strategies") or {}
        if isinstance(strategies, dict):
            strategies = strategies.get("strategies", [])
        if not strategies:
            return None
        top = strategies[0] if isinstance(strategies, list) else {}
        return {
            "type": top.get("type"),
            "value": top.get("value"),
            "score": top.get("score"),
        }

    @staticmethod
    async def detect_changes(
        db: AsyncSession,
        page_id: UUID,
        base_fetch_id: Optional[UUID] = None,
        current_fetch_id: Optional[UUID] = None,
    ) -> ChangeDetection:
        """
        ELEM-05: 检测两次抓取之间的元素变更

        对比 base（上一次）与 current（本次）抓取的元素列表，
        识别 added（新增）/removed（消失）/modified（定位器变更）三类。

        Args:
            db: 数据库会话
            page_id: 页面ID
            base_fetch_id: 基准抓取历史ID（None 则自动取上一次成功抓取）
            current_fetch_id: 当前抓取历史ID（None 则自动取最近一次抓取）

        Returns:
            ChangeDetection 记录（含聚合统计）
        """
        # 获取 page（拿 project_id）
        page_result = await db.execute(
            select(PageRepository).where(PageRepository.id == page_id)
        )
        page = page_result.scalar_one_or_none()
        if page is None:
            raise ValueError(f"Page {page_id} not found")

        # 自动确定 base/current fetch
        if current_fetch_id is None:
            cur_result = await db.execute(
                select(FetchHistory)
                .where(FetchHistory.page_id == page_id, FetchHistory.status == "success")
                .order_by(FetchHistory.fetch_time.desc())
                .limit(1)
            )
            current_fetch = cur_result.scalar_one_or_none()
            current_fetch_id = current_fetch.id if current_fetch else None

        if base_fetch_id is None and current_fetch_id is not None:
            base_result = await db.execute(
                select(FetchHistory)
                .where(
                    FetchHistory.page_id == page_id,
                    FetchHistory.status == "success",
                    FetchHistory.id != current_fetch_id,
                )
                .order_by(FetchHistory.fetch_time.desc())
                .limit(1)
            )
            base_fetch = base_result.scalar_one_or_none()
            base_fetch_id = base_fetch.id if base_fetch else None

        # 当前页面所有 active 元素即作为 current 快照
        cur_elems_result = await db.execute(
            select(ElementRepository).where(
                ElementRepository.page_id == page_id,
                ElementRepository.status == "active",
            )
        )
        current_elements = cur_elems_result.scalars().all()

        # base 快照：这里简化为与上次变更检测对比；若无历史，则全部视为新增
        # （完整实现应存储快照表；此处基于当前元素 + 历史变更检测推断）
        last_detection_result = await db.execute(
            select(ChangeDetection)
            .where(ChangeDetection.page_id == page_id)
            .order_by(ChangeDetection.check_time.desc())
            .limit(1)
        )
        last_detection = last_detection_result.scalar_one_or_none()

        # 构建 base 元素签名集合
        base_signatures: Dict[str, Dict[str, Any]] = {}
        if last_detection and last_detection.current_fetch_id:
            # 简化：以最近一次检测时的"已存在元素"为 base
            # 真实实现需快照表，这里用 last_detection 的 added+modified 作为已知存在集
            for item in (last_detection.added or []) + (last_detection.modified or []):
                sig = item.get("element_id") or ChangeDetectionService._element_signature(item)
                base_signatures[sig] = item
        else:
            # 首次检测：所有元素视为已存在（避免误报全部新增）
            for e in current_elements:
                base_signatures[ChangeDetectionService._element_signature(e.to_dict())] = e.to_dict()

        # 构建 current 元素映射
        current_map: Dict[str, Dict[str, Any]] = {}
        for e in current_elements:
            ed = e.to_dict()
            current_map[ChangeDetectionService._element_signature(ed)] = ed

        added: List[Dict[str, Any]] = []
        removed: List[Dict[str, Any]] = []
        modified: List[Dict[str, Any]] = []

        # 新增：current 有，base 无
        for sig, elem in current_map.items():
            if sig not in base_signatures:
                added.append({
                    "element_id": elem.get("element_id"),
                    "element_name": elem.get("element_name"),
                    "locator": ChangeDetectionService._locator_summary(elem),
                })

        # 消失：base 有，current 无
        for sig, elem in base_signatures.items():
            if sig not in current_map:
                removed.append({
                    "element_id": elem.get("element_id") if isinstance(elem, dict) else None,
                    "element_name": elem.get("element_name") if isinstance(elem, dict) else None,
                    "locator": ChangeDetectionService._locator_summary(elem) if isinstance(elem, dict) else None,
                })

        # 变更：都存在但定位器变化
        for sig, cur_elem in current_map.items():
            if sig in base_signatures:
                base_elem = base_signatures[sig]
                if not isinstance(base_elem, dict):
                    continue
                cur_loc = ChangeDetectionService._locator_summary(cur_elem)
                base_loc = ChangeDetectionService._locator_summary(base_elem)
                if cur_loc != base_loc and cur_loc is not None:
                    modified.append({
                        "element_id": cur_elem.get("element_id"),
                        "element_name": cur_elem.get("element_name"),
                        "old_locator": base_loc,
                        "new_locator": cur_loc,
                    })

        # 影响等级
        total_changes = len(added) + len(removed) + len(modified)
        if total_changes == 0:
            impact_level = "low"
        elif total_changes <= 5:
            impact_level = "medium"
        else:
            impact_level = "high"

        # 创建变更检测记录
        detection = ChangeDetection(
            page_id=page_id,
            project_id=page.project_id,
            base_fetch_id=base_fetch_id,
            current_fetch_id=current_fetch_id,
            added=added,
            removed=removed,
            modified=modified,
            added_count=len(added),
            removed_count=len(removed),
            modified_count=len(modified),
            affected_scripts=[],
            affected_script_count=0,
            impact_level=impact_level,
            status="pending",
        )
        db.add(detection)
        await db.commit()
        await db.refresh(detection)

        logger.info(
            f"Change detection for page {page_id}: "
            f"+{len(added)} -{len(removed)} ~{len(modified)} (impact={impact_level})"
        )
        return detection

    @staticmethod
    async def mark_affected_scripts(
        db: AsyncSession,
        detection_id: UUID,
        affected_scripts: List[Dict[str, Any]],
    ) -> ChangeDetection:
        """
        ELEM-06: 标记变更影响的脚本 (SCRIPT-07 联动)

        Args:
            db: 数据库会话
            detection_id: 变更检测记录ID
            affected_scripts: 受影响脚本列表 [{script_id, script_name, elements: [...]}]

        SCRIPT-07: 同时回写 ScriptAsset.last_status='affected',
        让脚本库高亮展示受变更影响的脚本。
        """
        from app.models.test_case import ScriptAsset
        from sqlalchemy import update

        result = await db.execute(
            select(ChangeDetection).where(ChangeDetection.id == detection_id)
        )
        detection = result.scalar_one_or_none()
        if detection is None:
            raise ValueError(f"ChangeDetection {detection_id} not found")

        detection.affected_scripts = affected_scripts
        detection.affected_script_count = len(affected_scripts)

        # 根据受影响脚本数量更新影响等级
        if len(affected_scripts) == 0:
            detection.impact_level = "low"
        elif len(affected_scripts) <= 3:
            detection.impact_level = "medium"
        else:
            detection.impact_level = "high"

        # SCRIPT-07 联动: 批量回写 ScriptAsset.last_status='affected'
        affected_ids = [
            s.get("script_id") for s in affected_scripts if s.get("script_id")
        ]
        if affected_ids:
            try:
                await db.execute(
                    update(ScriptAsset)
                    .where(ScriptAsset.id.in_(affected_ids))
                    .values(last_status="affected")
                )
            except Exception as e:
                logger.warning(f"Failed to write back ScriptAsset.last_status=affected: {e}")

        await db.commit()
        await db.refresh(detection)
        logger.info(
            f"Marked {len(affected_scripts)} affected scripts for detection {detection_id} "
            f"(wrote back last_status=affected to {len(affected_ids)} script assets)"
        )
        return detection

    @staticmethod
    async def update_locators_one_click(
        db: AsyncSession,
        detection_id: UUID,
    ) -> Dict[str, Any]:
        """
        ELEM-07: 一键更新受影响元素的定位器

        将 modified 元素的新定位器回写到 element_repository，
        并将变更检测记录状态置为 fixed。

        Args:
            db: 数据库会话
            detection_id: 变更检测记录ID

        Returns:
            {"updated_count": int, "failed_count": int, "updated_elements": [...]}
        """
        result = await db.execute(
            select(ChangeDetection).where(ChangeDetection.id == detection_id)
        )
        detection = result.scalar_one_or_none()
        if detection is None:
            raise ValueError(f"ChangeDetection {detection_id} not found")

        updated_elements = []
        failed_count = 0

        # 处理 modified 元素：用新定位器更新仓库
        for item in (detection.modified or []):
            element_id = item.get("element_id")
            new_locator = item.get("new_locator")
            if not element_id or not new_locator:
                failed_count += 1
                continue

            try:
                # 查找元素
                elem_result = await db.execute(
                    select(ElementRepository).where(
                        ElementRepository.page_id == detection.page_id,
                        ElementRepository.element_id == element_id,
                        ElementRepository.status == "active",
                    )
                )
                elem = elem_result.scalar_one_or_none()
                if elem is None:
                    failed_count += 1
                    continue

                # 构建新的 locator_strategies
                existing = elem.locator_strategies or {"strategies": []}
                strategies = existing.get("strategies", []) if isinstance(existing, dict) else []
                # 将新定位器置顶
                new_strategies = [new_locator] + [s for s in strategies if s.get("value") != new_locator.get("value")]
                elem.locator_strategies = {"strategies": new_strategies}
                elem.source = "healed"
                elem.last_verified_at = datetime.utcnow()
                updated_elements.append({"element_id": element_id, "element_name": item.get("element_name")})
            except Exception as e:
                logger.warning(f"Failed to update locator for {element_id}: {e}")
                failed_count += 1

        detection.status = "fixed"
        detection.fixed_at = datetime.utcnow()
        await db.commit()

        logger.info(
            f"One-click locator update for detection {detection_id}: "
            f"updated={len(updated_elements)}, failed={failed_count}"
        )
        return {
            "updated_count": len(updated_elements),
            "failed_count": failed_count,
            "updated_elements": updated_elements,
        }
