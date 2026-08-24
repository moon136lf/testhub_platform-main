"""
Hallucination Detector Service - Detect hallucinations in generated test cases
"""

import logging
from typing import Dict, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.models.element import ElementRepository, PageRepository

logger = logging.getLogger(__name__)


class HallucinationDetector:
    """幻觉检测服务"""

    def __init__(self, project_id: UUID, strategy: str = "mark"):
        """
        初始化幻觉检测器

        Args:
            project_id: 项目ID
            strategy: 检测策略（当前仅存储，未使用）
        """
        self.project_id = project_id
        self.strategy = strategy
        self.forbidden_keywords = ["观察", "查看", "验证", "检查", "确认", "看到", "显示", "观看", "浏览"]

    async def detect(self, db: AsyncSession, case_data: Dict) -> Dict:
        """
        检测用例是否存在幻觉

        Args:
            db: 数据库会话
            case_data: 用例数据，包含 steps 和 expected_result

        Returns:
            {
                "status": "normal"/"suspected",
                "reasons": [...],
                "confidence": float
            }
        """
        try:
            logger.info("Starting hallucination detection")

            reasons = []

            # Check forbidden keywords
            keyword_reasons = await self._check_keywords(case_data)
            reasons.extend(keyword_reasons)

            # Check element existence
            element_reasons = await self._check_elements(db, case_data)
            reasons.extend(element_reasons)

            # Determine status and confidence
            if reasons:
                status = "suspected"
                confidence = min(len(reasons) * 0.3, 1.0)
                logger.info(f"Hallucination suspected: {len(reasons)} reasons found")
            else:
                status = "normal"
                confidence = 1.0
                logger.info("No hallucination detected")

            return {
                "status": status,
                "reasons": reasons,
                "confidence": confidence
            }

        except Exception as e:
            logger.error(f"Hallucination detection failed: {e}")
            raise

    async def _check_keywords(self, case_data: Dict) -> List[str]:
        """
        检查steps和expected_result中的禁用词

        Args:
            case_data: 用例数据

        Returns:
            检测到的问题列表
        """
        reasons = []

        # Check steps
        steps = case_data.get("steps", [])
        for i, step in enumerate(steps):
            action = step.get("action", "")
            data = step.get("data", "")

            for keyword in self.forbidden_keywords:
                if keyword in action or keyword in data:
                    reasons.append(f"步骤{i+1}包含非自动化词汇「{keyword}」")

        # Check expected_result
        expected_result = case_data.get("expected_result", "")
        for keyword in self.forbidden_keywords:
            if keyword in expected_result:
                reasons.append(f"预期结果包含非自动化词汇「{keyword}」")

        return reasons

    async def _check_elements(self, db: AsyncSession, case_data: Dict) -> List[str]:
        """
        检查steps中的target是否在元素库中

        Args:
            db: 数据库会话
            case_data: 用例数据

        Returns:
            检测到的问题列表
        """
        reasons = []

        steps = case_data.get("steps", [])
        for i, step in enumerate(steps):
            target = step.get("target", "")

            if not target:
                continue

            # Check if element exists in repository
            exists = await self._element_exists(db, target)

            if not exists:
                reasons.append(f"步骤{i+1}引用的元素「{target}」不在元素库中")

        return reasons

    async def _element_exists(self, db: AsyncSession, element_desc: str) -> bool:
        """
        模糊匹配元素库

        Args:
            db: 数据库会话
            element_desc: 元素描述

        Returns:
            是否存在匹配的元素
        """
        try:
            # Query elements with fuzzy matching on element_id, element_name, or element_text
            query = (
                select(ElementRepository)
                .join(PageRepository, ElementRepository.page_id == PageRepository.id)
                .where(PageRepository.project_id == self.project_id)
                .where(
                    or_(
                        ElementRepository.element_id.ilike(func.concat('%', element_desc, '%')),
                        ElementRepository.element_name.ilike(func.concat('%', element_desc, '%')),
                        ElementRepository.element_text.ilike(func.concat('%', element_desc, '%')),
                    )
                )
            )

            result = await db.execute(query)
            elements = result.scalars().all()

            return len(elements) > 0

        except Exception as e:
            logger.error(f"Element existence check failed: {e}")
            return False
