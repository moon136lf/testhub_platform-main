"""脚本执行引擎 - 逐步执行 + 失败采集 + 回写 (#5a).

乙路径: 读 step_mapping 逐 step → 查元素库 → SmartLocator.locate_and_interact → 断言 → 失败采集.
自愈 Level1 复用 SmartLocator; Level2-4 留 #5b; AI 诊断留 #5c.
"""
import asyncio
import logging
import traceback
from typing import Optional, Dict, Any, List

from app.services.smart_locator import ElementNotFoundError

logger = logging.getLogger(__name__)


def classify_error(error: Exception) -> str:
    """错误四分类: locate_failed/timeout/assertion_failed/script_error."""
    if isinstance(error, ElementNotFoundError):
        return "locate_failed"
    if isinstance(error, asyncio.TimeoutError):
        return "timeout"
    if isinstance(error, AssertionError):
        return "assertion_failed"
    return "script_error"


async def collect_failure(page, step: int, error: Exception, storage=None) -> dict:
    """TRANS-04: 失败采集截图+DOM+堆栈. 浏览器已关则跳过采集, 不崩."""
    screenshot_url = None
    dom_snapshot = None
    if page is not None:
        try:
            screenshot = await page.screenshot()
            if storage is not None and screenshot:
                screenshot_url = await storage.upload_bytes(screenshot, f"fail_step{step}.png")
        except Exception as e:
            logger.warning(f"screenshot collect failed: {e}")
        try:
            dom_snapshot = await page.content()
            if dom_snapshot:
                dom_snapshot = dom_snapshot[:50000]
        except Exception as e:
            logger.warning(f"dom collect failed: {e}")
    # 用 error 实例自身的 traceback 格式化, 而非 traceback.format_exc()——后者依赖
    # 调用上下文处于 except 块, 在正常协程调用里会返回 'NoneType: None\n',
    # 无法体现错误类型. format_exception 始终包含异常类型名 + 消息.
    stack_trace = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    return {
        "error_type": classify_error(error),
        "error_msg": str(error)[:2000],
        "stack_trace": stack_trace,
        "screenshot_url": screenshot_url,
        "dom_snapshot": dom_snapshot,
    }
