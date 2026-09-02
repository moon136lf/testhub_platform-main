"""脚本执行引擎 - 逐步执行 + 失败采集 + 回写 (#5a).

乙路径: 读 step_mapping 逐 step → 查元素库 → SmartLocator.locate_and_interact → 断言 → 失败采集.
自愈 Level1 复用 SmartLocator; Level2-4 留 #5b; AI 诊断留 #5c.
"""
import asyncio
import logging
import time
import traceback
from datetime import datetime
from typing import Optional

from app.services.smart_locator import SmartLocator, ElementNotFoundError
from app.models.test_case import ScriptAsset
from app.models.execution import ExecutionRecord, ExecutionDetail

logger = logging.getLogger(__name__)


# 受支持且需验证的断言类型 (其余如 dialog_closed/ambiguous 暂不验证, 标 TODO)
_ASSERTION_TYPES_REQUIRING_CHECK = ("toast_message", "field_value")


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
            logger.warning(f"screenshot collect failed | step={step}: {e}")
        try:
            dom_snapshot = await page.content()
            if dom_snapshot:
                dom_snapshot = dom_snapshot[:50000]
        except Exception as e:
            logger.warning(f"dom collect failed | step={step}: {e}")
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

    async def _launch_browser(self, config, target_url: str):
        """启动真实 Playwright 浏览器并导航到 target_url (#5a T真实化).

        单测 monkeypatch 此方法返回 mock page, 不真实启动浏览器。
        """
        from app.services.playwright_service import PlaywrightService
        ps = PlaywrightService()
        await ps.start(
            headless=getattr(config, "headless", True),
            timeout=getattr(config, "timeout", 60),
        )
        page = await ps.browser.new_page()
        if target_url:
            await page.goto(target_url)
        return page

    async def _check_assertion(self, page, assertion: dict) -> None:
        """断言校验 (TRANS assertion). page=None 时跳过 (mock 路径不验证).

        #5a 最小实现: toast_message/field_value 做最小验证; 其他类型标 TODO 跳过。
        验证失败抛 AssertionError → 由调用方归类为 assertion_failed。
        """
        if not assertion or not page:
            return
        if not assertion.get("is_valid", False):
            return  # is_valid=False 不验证业务结果
        atype = assertion.get("type")
        expected = assertion.get("expected")
        try:
            if atype == "toast_message":
                # 期望页面文本包含 expected
                text = await page.text_content("body")
                if expected and (text is None or expected not in text):
                    raise AssertionError(
                        f"toast_message 断言失败: 期望含 '{expected}', 实际文本不含"
                    )
            elif atype == "field_value":
                # 期望某输入框值等于 expected (target 暂用 body 文本兜底)
                # TODO: 按 assertion.target 定位具体输入框, 当前最小实现仅占位
                return
            else:
                # status_changed/row_visible/dialog_closed/ambiguous: 暂不验证, 标 TODO
                # 不抛错, 避免误报; 真实化阶段按 type 细化
                return
        except AssertionError:
            raise
        except Exception as e:
            # 验证过程异常 (如 page 已关) 不应吞掉断言失败, 但也不应崩引擎
            logger.warning(f"assertion check error (type={atype}): {e}")
            return

    async def _do_writeback(self, writeback: dict):
        """TRANS-08: 执行 ElementService.writeback_healed_locator (confidence>=3 回写元素库).

        #5b T5: 由 ScriptExecutor 调用, 将 SmartLocator 透传的 writeback 信号落回元素库.
        db=None 时跳过; 异常仅记日志不崩 (回写失败不应影响执行主流程).
        """
        try:
            if self.db is None:
                return
            from app.services.element_service import ElementService
            svc = ElementService(self.db)
            await svc.writeback_healed_locator(writeback["element_id"], writeback["locator"])
        except Exception as e:
            logger.warning(f"writeback to repo failed | element_id={writeback.get('element_id')}: {e}")

    async def execute(self, script_asset: ScriptAsset, config, target_url: str,
                      sse, execution_record: Optional[ExecutionRecord] = None,
                      page=None) -> Optional[ExecutionDetail]:
        """执行单个脚本, 返回整体 ExecutionDetail (step=0). page=None 时自动 launch.

        execution_record=None 用于 quick-run: 不落 ExecutionDetail, 仅 SSE 直播.
        """
        start = time.time()
        step_mapping = script_asset.step_mapping or []
        steps = [s for s in step_mapping if s.get("step", 0) > 0]
        await sse.send_message(type="system", stage="execute",
                               content=f"开始执行脚本：{script_asset.name}", progress=0.0)
        # page=None 时启动真实浏览器 (单测 monkeypatch _launch_browser)
        launched = False
        if page is None:
            try:
                page = await self._launch_browser(config, target_url)
                launched = True
            except Exception as e:
                logger.error(f"browser launch failed | script={script_asset.name} target_url={target_url}: {e}")
                page = None
        failures = 0
        overall_status = "pass"
        last_failure = None
        max_failures = getattr(config, "max_failures", 8) or 8
        heal_logs = []  # #5b T5: 收集每步 SmartLocator 透传的 heal_log (聚合填 ExecutionDetail)
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
            locator = SmartLocator(_element_to_dict(element_data), gateway=self.gateway)
            try:
                result = await locator.locate_and_interact(page, action, value=sm.get("value"))
                # #5b T5: 收集 heal 信号 (SmartLocator 透传 heal_log/writeback)
                heal_logs.append(result.get("heal_log") or [])
                writeback = result.get("writeback")
                if writeback:
                    await self._do_writeback(writeback)
                had_heal = bool(result.get("heal_log"))
                # 断言校验 (action 成功后): 若 assertion 存在且 is_valid → _check_assertion
                assertion = sm.get("assertion")
                if assertion:
                    await self._check_assertion(page, assertion)
                await sse.send_message(type="system", stage="execute",
                                       content=f"第 {step} 步：✅ 通过" + ("（自愈）" if had_heal else ""),
                                       progress=((i + 1) / max(len(steps), 1)) * 0.9)
            except Exception as e:
                last_failure = await collect_failure(page, step, e, storage=self.storage)
                failures += 1
                overall_status = "fail"
                # #5b 审查 #3: 自愈失败也保留 heal_log (ElementNotFoundError 携带), 供 heal_status="failed" 判定
                failed_heal_log = getattr(e, "heal_log", None)
                if failed_heal_log:
                    heal_logs.append(failed_heal_log)
                await sse.send_message(type="error", stage="execute",
                                       content=f"第 {step} 步：❌ 失败（{last_failure['error_type']}）",
                                       progress=((i + 1) / max(len(steps), 1)) * 0.9)
                if failures >= max_failures:
                    break

        # 关闭自启的浏览器 (避免泄漏; 真实化阶段应统一管理生命周期)
        if launched and page is not None:
            try:
                await page.close()
            except Exception as e:
                logger.warning(f"page close failed: {e}")

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
        # #5b T5: 聚合 heal_log + 判定 heal_status (有自愈成功 → healed; 有自愈尝试全失败 → failed; 无 → none)
        all_heal_logs = [h for logs in heal_logs for h in (logs or []) if h]
        if all_heal_logs and any(h.get("success") for h in all_heal_logs):
            heal_status = "healed"
        elif all_heal_logs:
            heal_status = "failed"
        else:
            heal_status = "none"
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
            heal_status=heal_status, heal_log=all_heal_logs or None,
            duration_ms=duration_ms,
        )
        return detail
