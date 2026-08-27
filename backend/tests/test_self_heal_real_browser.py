"""#5b 审查修复: 真实 Playwright 冒烟测试 (守门).

审查 Critical #1: Level2/3/4 曾返回 `page.get_by_role(...)` Python API 表达式字符串,
传给 `page.locator()` 在真实浏览器抛 "Unknown engine". 本文件用真实 chromium 验证:
自愈返回的定位器必须是合法选择器字符串 (CSS/XPath/text=/role= 引擎语法).

无浏览器环境 (chromium 未装) 自动 skip.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

pytest.importorskip("playwright", reason="playwright not installed")

from app.services.self_heal_engine import SelfHealEngine


class FakeCache:
    async def record_heal_success(self, eid, info): return 1
    async def record_heal_failure(self, eid): return None
    async def should_writeback_to_repo(self, eid): return False
    async def get_writeback_locator(self, eid): return None


async def _new_page(content: str):
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.set_content(content)
    return pw, browser, page


def _element_data(name="用户名", text="用户名"):
    return {"element_id": "e1", "element_name": name,
            "locator_strategies": {"strategies": []}, "semantic_info": {"text": text}}


@pytest.mark.asyncio
async def test_dom_fuzz_returns_parsable_selector():
    """Level2: dom_fuzz 返回的选择器必须能被 page.locator() 解析并命中元素."""
    pw, browser, page = await _new_page('<input placeholder="用户名">')
    try:
        eng = SelfHealEngine(gateway=MagicMock(), element_cache=FakeCache())
        loc = await eng._heal_by_dom_fuzz(page, _element_data())
        assert loc is not None
        # 守门: 真实 page.locator() 能解析且命中 (mock 测试无法发现表达式字符串问题)
        count = await page.locator(loc).count()
        assert count >= 1, f"healed locator {loc!r} matched {count} elements in real browser"
    finally:
        await browser.close()
        await pw.stop()


@pytest.mark.asyncio
async def test_dom_fuzz_aria_hit_returns_aria_selector():
    """Level2: aria-label 命中时应返回 [aria-label=...] 选择器, 而非 text= (文本不存在)."""
    pw, browser, page = await _new_page('<button aria-label="登录">登</button>')
    try:
        eng = SelfHealEngine(gateway=MagicMock(), element_cache=FakeCache())
        loc = await eng._heal_by_dom_fuzz(page, _element_data(name="登录", text="登录"))
        assert loc is not None
        count = await page.locator(loc).count()
        assert count >= 1, f"healed locator {loc!r} matched {count} elements in real browser"
    finally:
        await browser.close()
        await pw.stop()


@pytest.mark.asyncio
async def test_ai_dom_llm_selector_output_parsed():
    """Level3: LLM 返回选择器格式输出 (清洗后) 应被 page.locator() 解析."""
    pw, browser, page = await _new_page('<button>登录</button>')
    try:
        gw = MagicMock()
        # LLM 按新提示词返回选择器, 但带 markdown 围栏 + 引号 (审查 #5 场景)
        gw.chat = AsyncMock(return_value={"content": '```text\nbutton:has-text("登录")\n```', "tokens": 50})
        eng = SelfHealEngine(gateway=gw, element_cache=FakeCache())
        loc = await eng._heal_by_ai_dom(page, _element_data(name="登录按钮", text="登录"))
        assert loc is not None
        count = await page.locator(loc).count()
        assert count >= 1, f"cleaned locator {loc!r} matched {count} elements"
    finally:
        await browser.close()
        await pw.stop()


@pytest.mark.asyncio
async def test_visual_llm_selector_output_parsed():
    """Level4: 多模态 LLM 返回选择器格式输出 (清洗后) 应被 page.locator() 解析."""
    pw, browser, page = await _new_page('<button>登录</button>')
    try:
        page.screenshot = AsyncMock(return_value=b"png")
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": '好的，定位器是：text="登录"', "tokens": 300})
        eng = SelfHealEngine(gateway=gw, element_cache=FakeCache())
        loc = await eng._heal_by_visual(page, _element_data(name="登录按钮", text="登录"))
        assert loc is not None
        count = await page.locator(loc).count()
        assert count >= 1, f"cleaned locator {loc!r} matched {count} elements"
    finally:
        await browser.close()
        await pw.stop()
