"""
测试 Playwright 定位器生成与验证核心逻辑 (Task 11)

覆盖：
- generate_locators_for_element: 8 种定位策略生成
- verify_and_score_locator: 唯一性加分/非唯一扣分/稳定性扣分
- extract_semantic_info: 坐标/上下文/aria 属性提取
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.playwright_service import (
    generate_locators_for_element,
    verify_and_score_locator,
    extract_semantic_info,
)


def _make_element(attrs=None, text="登录", tag="button", box=None):
    """构造 Mock Playwright Locator 元素"""
    attrs = attrs or {}
    element = AsyncMock()

    async def get_attribute(attr):
        return attrs.get(attr)

    element.get_attribute = get_attribute
    element.inner_text = AsyncMock(return_value=text)
    element.bounding_box = AsyncMock(return_value=box or {"x": 10, "y": 20, "width": 80, "height": 30})

    async def evaluate(script, *args):
        # 区分不同的 evaluate 调用：tagName / 复杂脚本
        s = script if isinstance(script, str) else ""
        if "tagName.toLowerCase()" in s and "parentElement" not in s and "siblings" not in s and "indexOf" not in s:
            return tag
        if "parentElement?.tagName" in s:
            return "form"
        if "Array.from(el.parentElement" in s:
            return ["form", "button", "input"]
        if "el.tagName.toLowerCase()" == s.strip():
            return tag
        # CSS path / XPath 脚本
        if "path = []" in s or "let path" in s:
            return f"{tag} > .container"
        return tag

    element.evaluate = evaluate
    return element


class TestGenerateLocatorsForElement:
    @pytest.mark.asyncio
    async def test_generates_id_strategy_when_id_present(self):
        element = _make_element(attrs={"id": "login-btn"})
        page = MagicMock()

        candidates = await generate_locators_for_element(page, element)

        assert any(c["type"] == "id" and c["value"] == "#login-btn" for c in candidates)
        # id 策略 base_score 应为 100
        id_cand = next(c for c in candidates if c["type"] == "id")
        assert id_cand["base_score"] == 100

    @pytest.mark.asyncio
    async def test_generates_data_testid_strategy(self):
        element = _make_element(attrs={"data-testid": "submit"})
        page = MagicMock()

        candidates = await generate_locators_for_element(page, element)

        testid = [c for c in candidates if c["type"] == "data-testid"]
        assert len(testid) == 1
        assert testid[0]["value"] == "[data-testid='submit']"
        assert testid[0]["base_score"] == 95

    @pytest.mark.asyncio
    async def test_generates_name_strategy(self):
        element = _make_element(attrs={"name": "username"}, tag="input")
        page = MagicMock()

        candidates = await generate_locators_for_element(page, element)

        name_cand = [c for c in candidates if c["type"] == "name"]
        assert len(name_cand) == 1
        assert name_cand[0]["value"] == "[name='username']"

    @pytest.mark.asyncio
    async def test_generates_role_text_strategy(self):
        element = _make_element(attrs={"role": "button"}, text="登录")
        page = MagicMock()

        candidates = await generate_locators_for_element(page, element)

        role_text = [c for c in candidates if c["type"] == "role-text"]
        assert len(role_text) == 1
        assert "登录" in role_text[0]["value"]

    @pytest.mark.asyncio
    async def test_generates_text_strategy(self):
        element = _make_element(text="提交")
        page = MagicMock()

        candidates = await generate_locators_for_element(page, element)

        text_cand = [c for c in candidates if c["type"] == "text"]
        assert len(text_cand) == 1

    @pytest.mark.asyncio
    async def test_always_generates_css_and_xpath(self):
        element = _make_element()
        page = MagicMock()

        candidates = await generate_locators_for_element(page, element)

        types = [c["type"] for c in candidates]
        assert "css" in types
        assert "xpath" in types

    @pytest.mark.asyncio
    async def test_skips_strategies_when_attribute_missing(self):
        """无 id/data-testid/name 的元素不应生成这些策略"""
        element = _make_element(attrs={}, text="登录")
        page = MagicMock()

        candidates = await generate_locators_for_element(page, element)

        types = [c["type"] for c in candidates]
        assert "id" not in types
        assert "data-testid" not in types
        assert "name" not in types


class TestVerifyAndScoreLocator:
    @pytest.mark.asyncio
    async def test_unique_locator_gets_bonus(self):
        page = MagicMock()
        target = AsyncMock()
        mock_found = AsyncMock()
        mock_found.evaluate = AsyncMock(return_value=True)
        # page.locator(value) 同步返回一个 AsyncMock，其 .all() 返回 [mock_found]
        locator_mock = AsyncMock()
        locator_mock.all = AsyncMock(return_value=[mock_found])
        page.locator = MagicMock(return_value=locator_mock)

        candidate = {"type": "id", "value": "#unique-id", "base_score": 100}
        result = await verify_and_score_locator(page, candidate, target)

        assert result is not None
        assert result["unique"] is True
        assert result["score"] == 120  # 100 + 20 唯一性加分
        assert result["verified"] is True

    @pytest.mark.asyncio
    async def test_non_unique_locator_gets_penalty(self):
        page = MagicMock()
        elem1 = AsyncMock()
        elem1.evaluate = AsyncMock(return_value=True)  # 第一个是目标
        elem2 = AsyncMock()
        elem2.evaluate = AsyncMock(return_value=False)
        locator_mock = AsyncMock()
        locator_mock.all = AsyncMock(return_value=[elem1, elem2])
        page.locator = MagicMock(return_value=locator_mock)

        candidate = {"type": "css", "value": ".btn", "base_score": 70}
        result = await verify_and_score_locator(page, candidate, elem1)

        assert result is not None
        assert result["unique"] is False
        assert result["score"] == 60  # 70 - 10 非唯一扣分

    @pytest.mark.asyncio
    async def test_returns_none_when_no_element_found(self):
        page = MagicMock()
        locator_mock = AsyncMock()
        locator_mock.all = AsyncMock(return_value=[])
        page.locator = MagicMock(return_value=locator_mock)

        candidate = {"type": "id", "value": "#missing", "base_score": 100}
        result = await verify_and_score_locator(page, candidate, AsyncMock())

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_target_not_in_results(self):
        page = MagicMock()
        found = AsyncMock()
        found.evaluate = AsyncMock(return_value=False)  # 找到的不是目标
        locator_mock = AsyncMock()
        locator_mock.all = AsyncMock(return_value=[found])
        page.locator = MagicMock(return_value=locator_mock)

        candidate = {"type": "css", "value": ".btn", "base_score": 70}
        result = await verify_and_score_locator(page, candidate, AsyncMock())

        assert result is None

    @pytest.mark.asyncio
    async def test_unstable_locator_gets_penalty(self):
        """含 nth-of-type/nth-child 的定位器应扣 15 分"""
        page = MagicMock()
        found = AsyncMock()
        found.evaluate = AsyncMock(return_value=True)
        locator_mock = AsyncMock()
        locator_mock.all = AsyncMock(return_value=[found])
        page.locator = MagicMock(return_value=locator_mock)

        candidate = {"type": "css", "value": "div:nth-of-type(2)", "base_score": 50}
        result = await verify_and_score_locator(page, candidate, found)

        assert result is not None
        # 50 + 20(唯一) - 15(不稳定) = 55
        assert result["score"] == 55


class TestExtractSemanticInfo:
    @pytest.mark.asyncio
    async def test_extracts_coords_from_bounding_box(self):
        element = _make_element(box={"x": 100, "y": 200, "width": 80, "height": 30})
        page = MagicMock()

        info = await extract_semantic_info(page, element)

        assert info["coords"]["x"] == 100
        assert info["coords"]["y"] == 200
        assert info["coords"]["width"] == 80
        assert info["coords"]["height"] == 30

    @pytest.mark.asyncio
    async def test_extracts_text_and_type(self):
        element = _make_element(text="登录按钮", tag="button")
        page = MagicMock()

        info = await extract_semantic_info(page, element)

        assert info["text"] == "登录按钮"
        assert info["type"] == "button"

    @pytest.mark.asyncio
    async def test_extracts_aria_attributes(self):
        element = _make_element(attrs={"aria-label": "提交", "role": "button", "placeholder": "请输入"})
        page = MagicMock()

        info = await extract_semantic_info(page, element)

        assert info["aria_label"] == "提交"
        assert info["aria_role"] == "button"
        assert info["placeholder"] == "请输入"

    @pytest.mark.asyncio
    async def test_extracts_context_parent_and_siblings(self):
        element = _make_element()
        page = MagicMock()

        info = await extract_semantic_info(page, element)

        assert "context" in info
        assert info["context"]["parent_tag"] == "form"
        assert isinstance(info["context"]["sibling_tags"], list)

    @pytest.mark.asyncio
    async def test_handles_missing_bounding_box(self):
        element = _make_element()
        element.bounding_box = AsyncMock(return_value=None)
        page = MagicMock()

        info = await extract_semantic_info(page, element)

        assert info["coords"]["x"] == 0
        assert info["coords"]["y"] == 0
