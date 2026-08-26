"""脚本执行引擎 - 逐步执行 + 失败采集 + 回写 (#5a).

乙路径: 读 step_mapping 逐 step → 查元素库 → SmartLocator.locate_and_interact → 断言 → 失败采集.
自愈 Level1 复用 SmartLocator; Level2-4 留 #5b; AI 诊断留 #5c.
"""
import asyncio
import logging
import time
import traceback
from datetime import datetime
from typing import Optional, Dict, Any, List

from app.services.smart_locator import SmartLocator, ElementNotFoundError
from app.models.test_case import ScriptAsset
from app.models.execution import ExecutionRecord, ExecutionDetail

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


def _element_to_dict(el) -> dict:
    """ElementRepository ORM 或 dict → SmartLocator 需的 dict."""
    if isinstance(el, dict):
        return el
    strategies = el.locator_strategies
    if isinstance(strategies, dict):
        strategies = strategies.get("strategies", [])
    return {
        "element_id": el.element_id,
        "element_name": el.element_name,
        "locator_strategies": {"strategies": strategies},
        "semantic_info": el.semantic_info,
    }


class ScriptExecutor:
    """脚本执行引擎 (乙路径). 逐步 step_mapping → 查元素库 → SmartLocator → 断言 → 失败采集 → 回写."""

    def __init__(self, db, gateway, storage, element_svc):
        self.db = db
        self.gateway = gateway
        self.storage = storage
        self.element_svc = element_svc

    async def execute(self, script_asset: ScriptAsset, config, target_url: str,
                      sse, execution_record: Optional[ExecutionRecord] = None,
                      page=None) -> Optional[ExecutionDetail]:
        """执行单个脚本, 返回整体 ExecutionDetail (step=0). page=None 时 mock 路径.

        execution_record=None 用于 quick-run: 不落 ExecutionDetail, 仅 SSE 直播.
        """
        start = time.time()
        step_mapping = script_asset.step_mapping or []
        steps = [s for s in step_mapping if s.get("step", 0) > 0]
        await sse.send_message(type="system", stage="execute",
                               content=f"开始执行脚本：{script_asset.name}", progress=0.0)
        failures = 0
        overall_status = "pass"
        last_failure = None
        max_failures = getattr(config, "max_failures", 8) or 8
        for i, sm in enumerate(steps):
            step = sm.get("step", i + 1)
            action = sm.get("action", "unknown")
            element_name = sm.get("element_name")
            await sse.send_message(type="system", stage="execute",
                                   content=f"第 {step}/{len(steps)} 步：{action} {element_name or ''}",
                                   progress=(i / max(len(steps), 1)) * 0.9)
            # 旧 step_mapping 兼容：缺 element_name → script_error
            if not element_name:
                last_failure = await collect_failure(None, step, ValueError(f"步骤 {step} 缺 element_name，无法执行"))
                failures += 1
                overall_status = "fail"
                if failures >= max_failures:
                    break
                continue
            # 查元素库
            element_data = await self.element_svc.find_by_name(str(script_asset.project_id), element_name)
            if not element_data:
                last_failure = await collect_failure(None, step, ValueError(f"元素库未找到：{element_name}"))
                failures += 1
                overall_status = "fail"
                if failures >= max_failures:
                    break
                continue
            # 执行
            locator = SmartLocator(_element_to_dict(element_data))
            try:
                await locator.locate_and_interact(page, action, value=sm.get("value"))
                await sse.send_message(type="system", stage="execute",
                                       content=f"第 {step} 步：✅ 通过",
                                       progress=((i + 1) / max(len(steps), 1)) * 0.9)
            except Exception as e:
                last_failure = await collect_failure(page, step, e, storage=self.storage)
                failures += 1
                overall_status = "fail"
                await sse.send_message(type="error", stage="execute",
                                       content=f"第 {step} 步：❌ 失败（{last_failure['error_type']}）",
                                       progress=((i + 1) / max(len(steps), 1)) * 0.9)
                if failures >= max_failures:
                    break

        # 回写 ScriptAsset
        script_asset.last_status = "passed" if overall_status == "pass" else "failed"
        script_asset.run_count = (script_asset.run_count or 0) + 1
        script_asset.last_run_at = datetime.utcnow()

        await sse.send_message(type="system", stage="execute",
                               content=f"执行完成：{'通过' if overall_status == 'pass' else '失败'}",
                               progress=1.0, tokens_used=getattr(self.gateway, "tokens", 0))
        # quick-run: 不落 ExecutionDetail (无 execution_record)
        if execution_record is None:
            return None
        duration_ms = int((time.time() - start) * 1000)
        detail = ExecutionDetail(
            execution_record_id=execution_record.id,
            script_id=getattr(script_asset, "id", None),
            step=0, action="overall",
            status=overall_status,
            error_type=last_failure["error_type"] if last_failure else None,
            error_msg=last_failure["error_msg"] if last_failure else None,
            stack_trace=last_failure["stack_trace"] if last_failure else None,
            screenshot_url=last_failure["screenshot_url"] if last_failure else None,
            dom_snapshot=last_failure["dom_snapshot"] if last_failure else None,
            heal_status="none", duration_ms=duration_ms,
        )
        return detail
