"""锚点定位 + 轴定位策略测试（缺口1+2）。

generate_locators_for_element 的 mock element 需支持：
- get_attribute(name) -> str | None
- inner_text() -> str
- evaluate(js, arg=None) -> 按 js 内特征返回（路径遍历 / 兄弟查询）
"""
import pytest
from unittest.mock import MagicMock
from app.services.playwright_locator_core import generate_locators_for_element


def make_page():
    return MagicMock()


def make_element(attrs=None, path_chain=None, evaluate_fn=None):
    """构造 mock element。

    attrs: 元素属性字典（含 _text 模拟 inner_text）
    path_chain: 锚点遍历 JS 的返回值（None 或 {"anchor": "#toolbar", "rel": "div:nth-of-type(2) > button"}）
    evaluate_fn: 自定义 evaluate 实现（覆盖默认）；签名 async fn(js, arg=None)
    """
    el = MagicMock()
    attrs = attrs or {}
    async def _get_attribute(name):
        return attrs.get(name)
    el.get_attribute = _get_attribute
    async def _inner_text():
        return attrs.get("_text", "")
    el.inner_text = _inner_text

    async def _default_evaluate(js, arg=None):
        if "MAX_UP" in js:  # 锚点遍历 JS 的特征标记（先判，因其也含 tagName 字样）
            return path_chain
        if "tagName" in js:
            return "button"
        return None
    el.evaluate = evaluate_fn or _default_evaluate
    return el


class TestAnchorStrategy:
    @pytest.mark.asyncio
    async def test_generates_anchor_locator_when_ancestor_has_id(self):
        """祖先 2 层内有 id=toolbar → 生成 anchor 策略。"""
        el = make_element(
            attrs={"_text": "查询", "class": "btn", "type": "button"},
            path_chain={"anchor": "#toolbar", "rel": "div:nth-of-type(2) > button"},
        )
        candidates = await generate_locators_for_element(make_page(), el)
        anchor = [c for c in candidates if c["type"] == "anchor"]
        assert anchor, "应有 anchor 策略候选"
        assert anchor[0]["value"] == "#toolbar > div:nth-of-type(2) > button"
        assert anchor[0]["base_score"] == 75

    @pytest.mark.asyncio
    async def test_no_anchor_when_no_stable_ancestor(self):
        """祖先链无 id/testid → 不生成 anchor。"""
        el = make_element(attrs={"_text": "x", "class": "c"}, path_chain=None)
        candidates = await generate_locators_for_element(make_page(), el)
        assert not [c for c in candidates if c["type"] == "anchor"]


class TestSiblingLabelStrategy:
    @pytest.mark.asyncio
    async def test_generates_sibling_label_for_input(self):
        """input 无 id/name，前兄弟 label 有文本 → 生成 sibling-label 轴定位。"""
        def make_eval(tag_holder):
            async def _evaluate(js, arg=None):
                if "MAX_UP" in js:
                    return None  # 无锚点
                if "tagName" in js and "previousElementSibling" not in js:
                    return "input"
                if "previousElementSibling" in js:
                    return {"label_text": "用户名", "tag": "input"}
                return None
            return _evaluate
        el = make_element(attrs={"_text": "", "type": "text"})
        el.evaluate = make_eval(el)
        candidates = await generate_locators_for_element(make_page(), el)
        axis = [c for c in candidates if c["type"] == "sibling-label"]
        assert axis, "应有 sibling-label 策略候选"
        assert "following-sibling::input" in axis[0]["value"]
        assert "用户名" in axis[0]["value"]
        assert axis[0]["base_score"] == 78

    @pytest.mark.asyncio
    async def test_no_sibling_label_for_button(self):
        """button 不生成 sibling-label（text 策略已覆盖）。"""
        async def _evaluate(js, arg=None):
            if "MAX_UP" in js:
                return None
            if "tagName" in js and "previousElementSibling" not in js:
                return "button"
            if "previousElementSibling" in js:
                return {"label_text": "按钮", "tag": "button"}
            return None
        el = make_element(attrs={"_text": "按钮", "type": "button"})
        el.evaluate = _evaluate
        candidates = await generate_locators_for_element(make_page(), el)
        assert not [c for c in candidates if c["type"] == "sibling-label"]

    @pytest.mark.asyncio
    async def test_apostrophe_label_uses_double_quoted_literal(self):
        """label 文本含单引号 → XPath 无反斜杠转义，应改用双引号字面量。"""
        async def _evaluate(js, arg=None):
            if "MAX_UP" in js:
                return None
            if "tagName" in js and "previousElementSibling" not in js:
                return "input"
            if "previousElementSibling" in js:
                return {"label_text": "it's 用户名", "tag": "input"}
            return None
        el = make_element(attrs={"_text": "", "type": "text"})
        el.evaluate = _evaluate
        candidates = await generate_locators_for_element(make_page(), el)
        axis = [c for c in candidates if c["type"] == "sibling-label"]
        assert axis, "应有 sibling-label 策略候选"
        assert 'contains(., "it\'s 用户名")' in axis[0]["value"]
        assert "\\" not in axis[0]["value"]

    @pytest.mark.asyncio
    async def test_container_label_uses_parent_axis(self):
        """label 包在前兄弟容器内 → 用 parent::*/following-sibling:: 轴。"""
        async def _evaluate(js, arg=None):
            if "MAX_UP" in js:
                return None
            if "tagName" in js and "previousElementSibling" not in js:
                return "input"
            if "previousElementSibling" in js:
                return {"label_text": "用户名", "tag": "input", "via_container": True}
            return None
        el = make_element(attrs={"_text": "", "type": "text"})
        el.evaluate = _evaluate
        candidates = await generate_locators_for_element(make_page(), el)
        axis = [c for c in candidates if c["type"] == "sibling-label"]
        assert axis, "应有 sibling-label 策略候选"
        assert "/parent::*/following-sibling::input" in axis[0]["value"]
        assert "//label[contains(., '用户名')]" in axis[0]["value"]


from app.services.playwright_locator_core import verify_and_score_locator


class TestVerifyNthExemption:
    """锚点路径自带 1-2 层 nth 是相对段定位所需，锚点已提供结构稳定性，非唯一时不应再扣 15。"""

    @pytest.mark.asyncio
    async def test_anchor_nth_not_penalized_when_not_unique(self):
        """锚点路径含 nth-of-type 且非唯一命中 → 只扣非唯一 30，不扣 nth 15。"""
        page = MagicMock()
        # 命中 2 个元素，目标是第一个（首个命中才有效，但非唯一）
        def make_found(is_target):
            f = MagicMock()
            async def _eval(js, arg=None):
                return is_target
            f.evaluate = _eval
            return f
        found = [make_found(True), make_found(False)]
        async def _all():
            return found
        page.locator = MagicMock(return_value=MagicMock(all=_all))
        target = MagicMock()
        async def _eh(js):
            return "handle"
        target.evaluate_handle = _eh

        result = await verify_and_score_locator(page, {
            "type": "anchor",
            "value": "#toolbar > div:nth-of-type(2) > button",
            "base_score": 75,
        }, target)
        # 75 - 30(非唯一) = 45；若无豁免则再 -15 = 30
        assert result["score"] == 45

    @pytest.mark.asyncio
    async def test_plain_css_nth_still_penalized_when_not_unique(self):
        """普通 css 全路径 nth 且非唯一 → 照扣（回归保护）。"""
        page = MagicMock()
        def make_found(is_target):
            f = MagicMock()
            async def _eval(js, arg=None):
                return is_target
            f.evaluate = _eval
            return f
        found = [make_found(True), make_found(False)]
        async def _all():
            return found
        page.locator = MagicMock(return_value=MagicMock(all=_all))
        target = MagicMock()
        async def _eh(js):
            return "handle"
        target.evaluate_handle = _eh

        result = await verify_and_score_locator(page, {
            "type": "css",
            "value": "div:nth-of-type(1) > span:nth-of-type(2)",
            "base_score": 50,
        }, target)
        # 50 - 30(非唯一) - 15(nth非唯一) = 5
        assert result["score"] == 5
