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


def parse_editor_steps(step_mapping):
    """解析编辑器行式步骤（seq 键）与旧 pipeline 步骤（step 键），统一为可执行列表。"""
    rows = [s for s in (step_mapping or []) if isinstance(s, dict)]
    return [s for s in rows if (s.get("step", 0) or s.get("seq", 0))]


async def _run_assert_db_query(sql: str):
    """assert_db 的 DB 查询（独立只读会话）。"""
    from sqlalchemy import text as _text
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await db.execute(_text("SET TRANSACTION READ ONLY"))
        result = await db.execute(_text(sql))
        row = result.scalar()
        return str(row) if row is not None else ""


async def dispatch_editor_action(page, step, expect_mod=None, db_query=None):
    """执行单条编辑器动作。返回 None=通过；AssertionError=断言失败；ValueError=未知操作。

    expect_mod: playwright.async_api.expect（由调用方传入，便于测试注入）"""
    action = step.get("action", "")
    target = step.get("target", "")
    value = step.get("value", "")

    if action == "navigate":
        await page.goto(value)
        return None
    if action == "click":
        await page.locator(target).click()
        return None
    if action == "input":
        await page.locator(target).fill(value)
        return None
    if action == "select":
        await page.locator(target).select_option(value)
        return None
    if action == "wait":
        try:
            ms = int(float(value or 1) * 1000)
        except (ValueError, TypeError):
            ms = 1000
        await page.wait_for_timeout(ms)
        return None
    if action == "assert_text":
        if expect_mod is None:
            from playwright.async_api import expect as expect_mod
        await expect_mod(page.locator(target)).to_have_text(value)
        return None
    if action == "assert_visible":
        if expect_mod is None:
            from playwright.async_api import expect as expect_mod
        await expect_mod(page.locator(target)).to_be_visible()
        return None
    if action == "assert_db":
        query = db_query or _run_assert_db_query
        actual = await query(value)
        if actual != str(step.get("expected", "")):
            raise AssertionError(
                f"DB断言失败: SQL「{value[:60]}」期望 {step.get('expected')} 实际 {actual}")
        return None
    raise ValueError(f"不支持的操作类型: {action}")


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

        实现类型: toast_message(页面含文本) / field_value(输入框值) /
        row_visible(表格行含文本) / dialog_closed(无 modal 可见) /
        status_changed(URL 或页面文本变化).
        ambiguous/is_valid=False → 不验证 (设计如此, 非桩).
        验证失败抛 AssertionError → 由调用方归类为 assertion_failed。
        """
        if not assertion or not page:
            return
        if not assertion.get("is_valid", False):
            return  # is_valid=False 不验证业务结果
        atype = assertion.get("type")
        expected = assertion.get("expected")
        target = assertion.get("target")
        try:
            if atype == "toast_message":
                # 期望页面文本包含 expected
                text = await page.text_content("body")
                if expected and (text is None or expected not in text):
                    raise AssertionError(
                        f"toast_message 断言失败: 期望含 '{expected}', 实际文本不含"
                    )
            elif atype == "field_value":
                # 期望输入框值为 expected；target 优先按文本占位定位，其次全局输入框
                if not expected:
                    return
                box = None
                if target:
                    # 先尝试 label/placeholder 文本关联定位
                    for sel in (
                        f'input[placeholder*="{target}"]',
                        f'input[normalize-space(@aria-label)="{target}"]' if target else None,
                    ):
                        if sel and await page.locator(sel).count() > 0:
                            box = page.locator(sel).first
                            break
                if box is None:
                    box = page.locator("input:visible").first
                actual = await box.input_value() if await box.count() else None
                if actual is None or expected not in str(actual):
                    raise AssertionError(
                        f"field_value 断言失败: 期望含 '{expected}', 实际='{actual}'"
                    )
            elif atype == "row_visible":
                # 期望表格/列表中出现含 expected 文本的行
                if not expected:
                    return
                row = page.locator(f"tr:has-text('{expected}'), li:has-text('{expected}')").first
                if await row.count() == 0 or not await row.is_visible():
                    raise AssertionError(
                        f"row_visible 断言失败: 未找到含 '{expected}' 的可见行"
                    )
            elif atype == "dialog_closed":
                # 期望 modal/弹窗已关闭（el-dialog overlay 消失）
                overlay = page.locator(".el-overlay:visible, .el-dialog:visible, [role=dialog]:visible")
                if await overlay.count() > 0:
                    raise AssertionError("dialog_closed 断言失败: 页面仍存在可见弹窗")
            elif atype == "status_changed":
                # 期望页面状态发生变化：URL 离开初始 URL，或页面文本包含 expected
                if expected:
                    text = await page.text_content("body")
                    if text is None or expected not in text:
                        raise AssertionError(
                            f"status_changed 断言失败: 期望含 '{expected}', 实际文本不含"
                        )
                else:
                    # 无 expected：与导航时 URL 比对
                    current = page.url
                    if target and current == target:
                        raise AssertionError("status_changed 断言失败: URL 未变化")
                    # 无 target 参照时无法判定，不误报
                    return
            else:
                # ambiguous 或未知类型: 不验证 (标记为不验证业务结果, 非桩)
                return
        except AssertionError:
            raise
        except Exception as e:
            # 验证过程异常 (如 page 已关) 不应吞掉断言失败, 但也不应崩引擎
            logger.warning(f"【脚本执行】断言校验异常(不算失败) | type={atype} 原因={e}")
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
            logger.warning(f"【脚本执行】定位器回写失败(非致命) | element_id={writeback.get('element_id')} 原因={e}")

    async def execute(self, script_asset: ScriptAsset, config, target_url: str,
                      sse, execution_record: Optional[ExecutionRecord] = None,
                      page=None) -> Optional[ExecutionDetail]:
        """执行单个脚本, 返回整体 ExecutionDetail (step=0). page=None 时自动 launch.

        execution_record=None 用于 quick-run: 不落 ExecutionDetail, 仅 SSE 直播.
        """
        start = time.time()
        step_mapping = script_asset.step_mapping or []
        steps = parse_editor_steps(step_mapping)
        # 阶段3 T0: 编辑器行式步骤（含 seq 键或含 navigate/wait/assert 类动作）走编辑器执行链路
        is_editor_format = any(
            s.get("seq") or s.get("action") in (
                "navigate", "wait", "assert_text", "assert_visible", "assert_db")
            for s in steps
        )
        await sse.send_message(type="system", stage="execute",
                               content=f"开始执行脚本：{script_asset.name}", progress=0.0)
        # page=None 时启动真实浏览器 (单测 monkeypatch _launch_browser)
        launched = False
        if page is None:
            try:
                page = await self._launch_browser(config, target_url)
                launched = True
            except Exception as e:
                logger.error(f"【脚本执行】浏览器启动失败 | script={script_asset.name} target={target_url} 原因={e} 建议=检查chromium安装与target可达性")
                page = None
        # 阶段3 T4: 登录态复用——config 带 env_credentials.login 则先走登录流程
        # （page 由 _launch_browser 创建，登录发生在该 page 所属 context 上，后续步骤天然带登录态；
        #   外部注入 page 时不重复登录）
        env_credentials = getattr(config, "env_credentials", None)
        if isinstance(env_credentials, dict) and env_credentials.get("login") and launched:
            from app.services.login_state_service import LoginStateService, LoginError
            try:
                await LoginStateService().ensure_state(
                    getattr(config, "env_id", "default"), env_credentials, page,
                    base_url=str(target_url or ""))
            except LoginError as e:
                logger.warning(f"登录态获取失败（非阻断，继续无登录执行）: {e}")

        failures = 0
        overall_status = "pass"
        last_failure = None
        max_failures = getattr(config, "max_failures", 8) or 8
        heal_logs = []  # #5b T5: 收集每步 SmartLocator 透传的 heal_log (聚合填 ExecutionDetail)
        if is_editor_format:
            # 编辑器行式步骤: target 即定位符, 不经元素库 (阶段3 T0)
            from playwright.async_api import expect as _async_expect
            for i, sm in enumerate(steps):
                step = sm.get("seq") or i + 1
                action = sm.get("action", "unknown")
                await sse.send_message(type="system", stage="execute",
                                       content=f"第 {step}/{len(steps)} 步：{action} {sm.get('element_name') or sm.get('target') or ''}",
                                       progress=(i / max(len(steps), 1)) * 0.9)
                try:
                    await dispatch_editor_action(page, sm, _async_expect)
                    await sse.send_message(type="system", stage="execute",
                                           content=f"第 {step} 步：✅ 通过",
                                           progress=((i + 1) / max(len(steps), 1)) * 0.9)
                except Exception as e:
                    last_failure = await collect_failure(page, step, e, storage=self.storage)
                    # 阶段3 T4: 执行失败时若被踢回登录页 → 失效登录态（下次重登）
                    if page is not None and "login" in (getattr(page, "url", "") or ""):
                        from app.services.login_state_service import LoginStateService
                        await LoginStateService().invalidate(getattr(config, "env_id", "default"))
                    failures += 1
                    overall_status = "fail"
                    await sse.send_message(type="error", stage="execute",
                                           content=f"第 {step} 步：❌ 失败（{last_failure['error_type']}）",
                                           progress=((i + 1) / max(len(steps), 1)) * 0.9)
                    if failures >= max_failures:
                        break
        else:
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
                    # 阶段3 T4: 执行失败时若被踢回登录页 → 失效登录态（下次重登）
                    if page is not None and "login" in (getattr(page, "url", "") or ""):
                        from app.services.login_state_service import LoginStateService
                        await LoginStateService().invalidate(getattr(config, "env_id", "default"))
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
        logger.info(f"【脚本执行】执行完成 | script={script_asset.name} 结果={overall_status} "
                    f"失败步数={failures} 耗时={int((time.time() - start) * 1000)}ms")
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
