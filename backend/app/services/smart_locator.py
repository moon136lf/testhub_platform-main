"""
Smart Locator - 智能定位器（支持降级和自愈）(Task 16)

执行层次：
1. 已验证定位器：按 score 降序逐个尝试，命中即操作
2. 自愈兜底：所有定位器失败时，用 semantic_info 调用 playwright-healer
3. 完全失败：抛 ElementNotFoundError

置信度回写（§8.2.8）：
- 自愈成功：confidence +1，连续失败计数归零；confidence >= 3 时回写仓库
- 自愈失败：confidence -1，连续失败 3 次删除缓存
"""

import logging
from typing import Dict, Any, Optional

from app.services.element_cache_service import ElementCacheService

logger = logging.getLogger(__name__)


class ElementNotFoundError(Exception):
    """元素未找到异常：所有定位器策略与自愈均失败

    heal_log: 自愈失败时携带各级尝试记录 (供 ScriptExecutor 落 ExecutionDetail.heal_log,
    审查 #3: 失败的自愈尝试也应可见, 且 heal_status 可判 "failed").
    """

    def __init__(self, message: str, heal_log: Optional[list] = None):
        super().__init__(message)
        self.heal_log = heal_log


class SmartLocator:
    """智能定位器 - 支持降级和自愈"""

    def __init__(self, element_data: Dict[str, Any], gateway=None):
        self.element_name = element_data.get("element_name", "unknown")
        self.element_id = element_data.get("element_id")
        self.locator_strategies = element_data["locator_strategies"]["strategies"]
        self.semantic_info = element_data.get("semantic_info")
        self.gateway = gateway

    async def locate_and_interact(self, page, action: str, **kwargs) -> Dict[str, Any]:
        """
        定位元素并执行操作（带自动降级 + 自愈）

        Args:
            page: Playwright Page 对象
            action: 操作类型 (click/fill/select/check/uncheck)
            **kwargs: 操作参数（如 fill 的 value）

        Returns:
            {"status": "success", "action": action}

        Raises:
            ElementNotFoundError: 所有定位器和自愈都失败
        """
        # 预校验操作类型，不支持的直接抛 ValueError（不走降级/自愈）
        supported_actions = {"click", "fill", "select", "check", "uncheck"}
        if action not in supported_actions:
            raise ValueError(f"Unsupported action: {action}")

        # 第 1 层：按 score 降序尝试已验证定位器
        sorted_strategies = sorted(
            self.locator_strategies,
            key=lambda x: x.get("score", 0),
            reverse=True,
        )

        for strategy in sorted_strategies:
            try:
                locator_value = strategy["value"]
                if strategy["type"] == "xpath":
                    locator = page.locator(f"xpath={locator_value}")
                else:
                    locator = page.locator(locator_value)

                # 等待元素出现（5 秒超时）
                await locator.wait_for(state="visible", timeout=5000)

                # 执行操作
                result = await self._perform_action(locator, action, **kwargs)

                logger.info(
                    f"✅ Element '{self.element_name}' located by {strategy['type']} "
                    f"({strategy['value']}, score={strategy.get('score')})"
                )
                return result

            except Exception as e:
                logger.warning(
                    f"⚠️ Strategy {strategy['type']} failed for '{self.element_name}': {e}"
                )
                continue

        # 第 2 层：所有定位器失败，尝试自愈
        if self.semantic_info:
            try:
                logger.info(f"【自愈引擎】触发自愈 | 元素={self.element_name} (定位器全失败, Level1-4 尝试中)")
                result = await self._self_heal_and_interact(page, action, **kwargs)
                logger.info(f"【自愈引擎】自愈成功 | 元素={self.element_name}")
                return result
            except Exception as e:
                logger.error(f"【自愈引擎】自愈失败(Level1-4全失败) | 元素={self.element_name} 原因={e} 建议=检查页面是否改版")

        # 第 3 层：完全失败
        raise ElementNotFoundError(
            f"Element '{self.element_name}' cannot be located. "
            f"Tried {len(sorted_strategies)} strategies and self-healing."
        )

    async def _perform_action(self, locator, action: str, **kwargs) -> Dict[str, Any]:
        """执行具体操作"""
        if action == "click":
            await locator.click()
        elif action == "fill":
            await locator.fill(kwargs.get("value", ""))
        elif action == "select":
            await locator.select_option(kwargs.get("value", ""))
        elif action == "check":
            await locator.check()
        elif action == "uncheck":
            await locator.uncheck()
        else:
            # 不支持的操作直接抛出，不进入降级/自愈流程
            raise ValueError(f"Unsupported action: {action}")

        return {"status": "success", "action": action}

    async def _self_heal_and_interact(
        self, page, action: str, **kwargs
    ) -> Dict[str, Any]:
        """自愈定位 (Level1-4 via SelfHealEngine).

        委托 SelfHealEngine 逐级尝试 semantic/dom_fuzz/ai_dom/visual:
        - 命中: 用 healed locator 执行操作, 返回带 heal_log/writeback 的结果
        - 全失败: 抛 ElementNotFoundError (失败记录由引擎负责)

        TODO: 集成 playwright-healer 库做更智能的自愈
        """
        from app.services.self_heal_engine import SelfHealEngine
        engine = SelfHealEngine(self.gateway, ElementCacheService)
        result = await engine.heal(page, self._element_data_dict(), action, **kwargs)

        if not result["success"]:
            # 失败记录由 SelfHealEngine._on_heal_failure 统一负责 (#5b 审查 #2:
            # 此处不再重复 record_heal_failure, 避免 failure_count 双计)
            raise ElementNotFoundError(
                f"Element '{self.element_name}' self-heal failed (Level1-4 all failed)",
                heal_log=result.get("heal_log") or [],
            )

        # 命中: 用 healed locator 执行操作
        locator = page.locator(result["locator"])
        await locator.wait_for(state="visible", timeout=5000)
        action_result = await self._perform_action(locator, action, **kwargs)
        action_result["heal_log"] = result.get("heal_log", [])
        action_result["writeback"] = result.get("writeback")
        return action_result

    def _element_data_dict(self) -> dict:
        """重建 SmartLocator 构造所需的 element_data dict (供 SelfHealEngine 使用)."""
        return {
            "element_id": self.element_id,
            "element_name": self.element_name,
            "locator_strategies": {"strategies": self.locator_strategies},
            "semantic_info": self.semantic_info,
        }

    async def _heal_by_semantic(self, page) -> Optional[str]:
        """基于语义信息构建候选定位器并尝试 (Level1 逻辑, 供 SelfHealEngine 复用)."""
        if not self.semantic_info:
            return None

        candidates = []

        # 优先级：text > aria-label > role > 坐标
        text = self.semantic_info.get("text")
        if text:
            candidates.append(f":has-text('{text}')")

        aria_label = self.semantic_info.get("aria_label")
        if aria_label:
            candidates.append(f"[aria-label='{aria_label}']")

        aria_role = self.semantic_info.get("aria_role")
        elem_type = self.semantic_info.get("type", "")
        if aria_role:
            candidates.append(f"[role='{aria_role}']")
        if elem_type:
            candidates.append(elem_type)

        # 逐个尝试候选定位器
        for value in candidates:
            try:
                locator = page.locator(value)
                if await locator.count() > 0:
                    return value
            except Exception:
                continue

        return None
