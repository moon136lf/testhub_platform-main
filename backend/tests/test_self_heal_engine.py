"""Self-heal engine tests (mock page/LLM/cache)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.self_heal_engine import SelfHealEngine


def asyncio_run(coro): return asyncio.run(coro)


class FakeEl:
    """模拟 Playwright ElementHandle."""
    def __init__(self, text="", aria="", visible=True):
        self._text = text; self._aria = aria; self._visible = visible
    async def text_content(self): return self._text
    async def get_attribute(self, name): return self._aria if name == "aria-label" else None
    async def is_visible(self): return self._visible


class FakePage:
    def __init__(self, elements):
        self._elements = elements  # dict selector -> [FakeEl]
    async def query_selector_all(self, selector):
        return self._elements.get(selector, [])


class FakeCache:
    def __init__(self): self.calls = []
    async def record_heal_success(self, eid, info): self.calls.append(("success", eid, info)); return 1
    async def record_heal_failure(self, eid): self.calls.append(("failure", eid))
    async def should_writeback_to_repo(self, eid): return False
    async def get_writeback_locator(self, eid): return None


class TestHealByDomFuzz:
    def _element_data(self):
        return {"element_id": "e1", "element_name": "用户名",
                "locator_strategies": {"strategies": []}, "semantic_info": {"text": "用户名"}}

    def test_dom_fuzz_matches_high_score(self):
        page = FakePage({"input": [FakeEl(text="用户名", aria="用户名")]})
        gw = MagicMock()
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_dom_fuzz(page, self._element_data()))
        # score 应 >= 70, 命中返回定位器
        assert result is not None

    def test_dom_fuzz_no_match_returns_none(self):
        page = FakePage({"input": [FakeEl(text="完全不相关的东西")]})
        gw = MagicMock()
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_dom_fuzz(page, self._element_data()))
        assert result is None


class TestHealByAiDom:
    def _element_data(self):
        return {"element_id": "e1", "element_name": "登录按钮",
                "locator_strategies": {"strategies": []}, "semantic_info": {"text": "登录"}}

    def test_ai_dom_returns_locator_from_llm(self):
        """LLM 按新提示词返回选择器字符串 (审查 Critical #1: 禁 page.get_by_* 表达式)."""
        page = MagicMock()
        page.content = AsyncMock(return_value="<html><button>登录</button></html>")
        loc = MagicMock()
        loc.wait_for = AsyncMock()
        page.locator = MagicMock(return_value=loc)
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "text=\"登录\"", "tokens": 50})
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_ai_dom(page, self._element_data()))
        assert result == "text=\"登录\""

    def test_ai_dom_rejects_get_by_expression(self):
        """审查 Critical #1: LLM 违约返回 page.get_by_*(...) 表达式 → 清洗拒绝 → None."""
        page = MagicMock()
        page.content = AsyncMock(return_value="<html><button>登录</button></html>")
        loc = MagicMock()
        loc.wait_for = AsyncMock()
        page.locator = MagicMock(return_value=loc)
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "page.get_by_role(\"button\", name=\"登录\")", "tokens": 50})
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_ai_dom(page, self._element_data()))
        assert result is None

    def test_ai_dom_invalid_locator_returns_none(self):
        page = MagicMock()
        page.content = AsyncMock(return_value="<html></html>")
        loc = MagicMock()
        loc.wait_for = AsyncMock(side_effect=Exception("not found"))
        page.locator = MagicMock(return_value=loc)
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "page.bogus()", "tokens": 10})
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_ai_dom(page, self._element_data()))
        assert result is None


class TestHealStateMachine:
    def _element_data(self):
        return {"element_id": "e1", "element_name": "用户名",
                "locator_strategies": {"strategies": []}, "semantic_info": {"text": "用户名"}}

    def test_heal_level1_success(self):
        page = MagicMock()
        gw = MagicMock()
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        # mock Level1 命中
        eng._heal_by_semantic = AsyncMock(return_value="page.get_by_label(\"用户名\")")
        result = asyncio_run(eng.heal(page, self._element_data(), "fill", value="admin"))
        assert result["success"] is True
        assert result["strategy"] == "semantic"
        assert len(result["heal_log"]) == 1

    def test_heal_all_fail(self):
        page = MagicMock()
        gw = MagicMock()
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        eng._heal_by_semantic = AsyncMock(return_value=None)
        eng._heal_by_dom_fuzz = AsyncMock(return_value=None)
        eng._heal_by_ai_dom = AsyncMock(return_value=None)
        result = asyncio_run(eng.heal(page, self._element_data(), "fill"))
        assert result["success"] is False
        assert ("failure", "e1") in cache.calls

    def test_heal_falls_through_to_level2(self):
        page = MagicMock()
        gw = MagicMock()
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        eng._heal_by_semantic = AsyncMock(return_value=None)
        eng._heal_by_dom_fuzz = AsyncMock(return_value="page.get_by_text(\"用户名\")")
        result = asyncio_run(eng.heal(page, self._element_data(), "fill"))
        assert result["success"] is True
        assert result["strategy"] == "dom_fuzz"
        assert len(result["heal_log"]) == 2  # Level1 失败 + Level2 成功


class TestWritebackSignal:
    def test_writeback_signal_when_confidence_high(self):
        page = MagicMock()
        gw = MagicMock()
        cache = MagicMock()
        cache.record_heal_success = AsyncMock(return_value=1)
        cache.should_writeback_to_repo = AsyncMock(return_value=True)
        cache.get_writeback_locator = AsyncMock(return_value={"type": "label", "value": "用户名"})
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        eng._heal_by_semantic = AsyncMock(return_value="page.get_by_label(\"用户名\")")
        result = asyncio_run(eng.heal(page, {"element_id": "e1", "element_name": "用户名",
                                              "locator_strategies": {"strategies": []}, "semantic_info": {}}, "fill"))
        assert result["success"] is True
        assert result["writeback"] is not None
        assert result["writeback"]["element_id"] == "e1"

    def test_no_writeback_below_confidence_threshold(self):
        """审查 #9: confidence 未到阈值 (should_writeback=False) → writeback 为 None, 不回写."""
        page = MagicMock()
        gw = MagicMock()
        cache = MagicMock()
        cache.record_heal_success = AsyncMock(return_value=1)
        cache.should_writeback_to_repo = AsyncMock(return_value=False)  # confidence < 3
        cache.get_writeback_locator = AsyncMock(return_value={"type": "label", "value": "x"})
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        eng._heal_by_semantic = AsyncMock(return_value="text=\"用户名\"")
        result = asyncio_run(eng.heal(page, {"element_id": "e1", "element_name": "用户名",
                                              "locator_strategies": {"strategies": []}, "semantic_info": {}}, "fill"))
        assert result["success"] is True
        assert result["writeback"] is None  # 未到阈值不产生回写信号
        cache.get_writeback_locator.assert_not_awaited()

    def test_heal_log_includes_locator_field(self):
        """审查 #8: heal_log 条目带 locator (诊断价值)."""
        page = MagicMock()
        gw = MagicMock()
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        eng._heal_by_semantic = AsyncMock(return_value="text=\"用户名\"")
        result = asyncio_run(eng.heal(page, {"element_id": "e1", "element_name": "用户名",
                                              "locator_strategies": {"strategies": []}, "semantic_info": {}}, "fill"))
        entry = result["heal_log"][0]
        assert entry["locator"] == "text=\"用户名\""
        assert entry["success"] is True


class TestHealByVisual:
    def _element_data(self):
        return {"element_id": "e1", "element_name": "登录按钮",
                "locator_strategies": {"strategies": []}, "semantic_info": {"text": "登录"}}

    def test_visual_returns_locator_from_multimodal(self):
        """Level4: 截图+base64 发 moonshot 多模态, LLM 返回选择器, 验证命中."""
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=b"fake-png-bytes")
        page.locator = MagicMock(return_value=MagicMock(wait_for=AsyncMock()))
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "role=button[name=\"登录\"]", "tokens": 300})
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_visual(page, self._element_data()))
        assert result == "role=button[name=\"登录\"]"
        # 验证 chat 被调, 且 provider="moonshot"
        gw.chat.assert_awaited_once()
        call_kwargs = gw.chat.call_args
        assert call_kwargs.kwargs.get("provider") == "moonshot"

    def test_visual_rejects_get_by_expression(self):
        """审查 Critical #1: LLM 违约返回 page.get_by_*(...) 表达式 → 清洗拒绝 → None."""
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=b"png")
        page.locator = MagicMock(return_value=MagicMock(wait_for=AsyncMock()))
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "page.get_by_role(\"button\", name=\"登录\")", "tokens": 300})
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_visual(page, self._element_data()))
        assert result is None

    def test_visual_invalid_locator_returns_none(self):
        """Level4: LLM 返回无效定位器, 验证失败返回 None."""
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=b"png")
        bad_loc = MagicMock()
        bad_loc.wait_for = AsyncMock(side_effect=Exception("not found"))
        page.locator = MagicMock(return_value=bad_loc)
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "page.bogus()", "tokens": 50})
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_visual(page, self._element_data()))
        assert result is None

    def test_visual_screenshot_fail_returns_none(self):
        """Level4: 截图失败返回 None."""
        page = MagicMock()
        page.screenshot = AsyncMock(side_effect=Exception("browser closed"))
        gw = MagicMock()
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_visual(page, self._element_data()))
        assert result is None

    def test_visual_oversized_screenshot_downscaled(self):
        """审查 #6: 超宽截图 (1920px) 发给 LLM 前缩放, payload 变小."""
        import io
        from PIL import Image
        from app.services.self_heal_engine import VISUAL_MAX_WIDTH
        img = Image.new("RGB", (1920, 1080), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=buf.getvalue())
        page.locator = MagicMock(return_value=MagicMock(wait_for=AsyncMock()))
        captured = {}
        gw = MagicMock()
        gw.chat = AsyncMock(side_effect=lambda m, **kw: (captured.update(m=m) or {"content": "text=\"登录\"", "tokens": 100}))
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        result = asyncio_run(eng._heal_by_visual(page, self._element_data()))
        assert result == "text=\"登录\""
        # 缩放验证: image_url 里 base64 解出的图宽 <= 1280
        img_url = captured["m"][0]["content"][1]["image_url"]["url"]
        import base64
        raw = base64.b64decode(img_url.split(",", 1)[1])
        out = Image.open(io.BytesIO(raw))
        assert out.width <= VISUAL_MAX_WIDTH

    def test_heal_falls_through_to_level4(self):
        """heal() Level1-3 全失败 -> Level4 命中."""
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=b"png")
        page.locator = MagicMock(return_value=MagicMock(wait_for=AsyncMock()))
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "text=\"登录\"", "tokens": 200})
        cache = FakeCache()
        eng = SelfHealEngine(gateway=gw, element_cache=cache)
        eng._heal_by_semantic = AsyncMock(return_value=None)
        eng._heal_by_dom_fuzz = AsyncMock(return_value=None)
        eng._heal_by_ai_dom = AsyncMock(return_value=None)
        result = asyncio_run(eng.heal(page, self._element_data(), "click"))
        assert result["success"] is True
        assert result["strategy"] == "visual"
        assert len(result["heal_log"]) == 4  # L1-L4


class TestCleanLlmLocator:
    """审查 #5: LLM 输出清洗 (markdown 围栏 / 杂讯 / 引号 / get_by_* 拒绝)."""

    def test_strips_markdown_fence(self):
        from app.services.self_heal_engine import SelfHealEngine
        assert SelfHealEngine._clean_llm_locator('```text\nbutton:has-text("登录")\n```') == 'button:has-text("登录")'

    def test_extracts_locator_from_noisy_sentence(self):
        from app.services.self_heal_engine import SelfHealEngine
        assert SelfHealEngine._clean_llm_locator('好的，定位器是：text="登录"') == 'text="登录"'
        assert SelfHealEngine._clean_llm_locator('定位器是 [aria-label="用户名"]') == '[aria-label="用户名"]'

    def test_plain_locator_passthrough(self):
        from app.services.self_heal_engine import SelfHealEngine
        assert SelfHealEngine._clean_llm_locator('text="登录"') == 'text="登录"'

    def test_rejects_get_by_expression(self):
        """审查 Critical #1: page.get_by_*(...) 表达式拒绝 (page.locator() 不认)."""
        from app.services.self_heal_engine import SelfHealEngine
        assert SelfHealEngine._clean_llm_locator('page.get_by_role("button", name="登录")') is None
        assert SelfHealEngine._clean_llm_locator('page.get_by_text("登录")') is None

    def test_empty_returns_none(self):
        from app.services.self_heal_engine import SelfHealEngine
        assert SelfHealEngine._clean_llm_locator("") is None
        assert SelfHealEngine._clean_llm_locator(None) is None


class TestElementServiceWriteback:
    def test_writeback_updates_element(self):
        from app.services.element_service import ElementService
        db = MagicMock()
        el = MagicMock()
        el.element_id = "e1"
        el.locator_strategies = None
        el.source = "manual"
        el.confidence = 3
        result = MagicMock()
        result.scalar_one_or_none.return_value = el
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()
        svc = ElementService(db)
        ok = asyncio_run(svc.writeback_healed_locator("e1", {"type": "label", "value": "用户名"}))
        assert ok is True
        assert el.source == "healed"
        assert el.confidence == 4
        db.flush.assert_awaited_once()
