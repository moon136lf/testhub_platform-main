"""自愈引擎 Level1-3 状态机 (#5b).

Level1 semantic (复用 SmartLocator 逻辑) → Level2 rapidfuzz DOM 模糊 → Level3 AI DOM (LLM).
每级命中: record_heal_success + confidence+1 + 检查回写; 失败: record_heal_failure + 降级.
全失败抛 ElementNotFoundError. 透明接入 SmartLocator.
"""
import logging
from typing import Optional, Dict, Any, List

from app.services.smart_locator import ElementNotFoundError

logger = logging.getLogger(__name__)

# DOM 模糊匹配阈值
FUZZ_SCORE_THRESHOLD = 70
FUZZ_TOP_K = 5
DOM_TRUNCATE = 20000

# 可交互元素 selector 列表
INTERACTIVE_SELECTORS = [
    "button", "a", "input", "select", "textarea",
    "[role='button']", "[role='link']", "[role='checkbox']", "[role='menuitem']",
]


class SelfHealEngine:
    """自愈引擎 Level1-3."""

    def __init__(self, gateway, element_cache):
        self.gateway = gateway
        self.element_cache = element_cache

    async def heal(self, page, element_data: dict, action: str, **kw) -> dict:
        """逐级自愈, 返回 {success, locator, strategy, heal_log, writeback}."""
        heal_log = []
        # Level1: semantic
        loc = await self._heal_by_semantic(page, element_data)
        heal_log.append({"level": 1, "strategy": "semantic", "success": loc is not None})
        if loc:
            wb = await self._on_heal_success(element_data, loc, "semantic")
            return {"success": True, "locator": loc, "strategy": "semantic", "heal_log": heal_log, "writeback": wb}
        # Level2: dom_fuzz
        loc = await self._heal_by_dom_fuzz(page, element_data)
        heal_log.append({"level": 2, "strategy": "dom_fuzz", "success": loc is not None})
        if loc:
            wb = await self._on_heal_success(element_data, loc, "dom_fuzz")
            return {"success": True, "locator": loc, "strategy": "dom_fuzz", "heal_log": heal_log, "writeback": wb}
        # Level3: ai_dom
        loc = await self._heal_by_ai_dom(page, element_data)
        heal_log.append({"level": 3, "strategy": "ai_dom", "success": loc is not None})
        if loc:
            wb = await self._on_heal_success(element_data, loc, "ai_dom")
            return {"success": True, "locator": loc, "strategy": "ai_dom", "heal_log": heal_log, "writeback": wb}
        # 全失败
        await self._on_heal_failure(element_data)
        return {"success": False, "locator": None, "strategy": None, "heal_log": heal_log, "writeback": None}

    async def _heal_by_semantic(self, page, element_data: dict) -> Optional[str]:
        """Level1: 复用 SmartLocator semantic 自愈逻辑 (text/aria/role 候选)."""
        from app.services.smart_locator import SmartLocator
        sl = SmartLocator(element_data)
        return await sl._heal_by_semantic(page)

    async def _heal_by_dom_fuzz(self, page, element_data: dict) -> Optional[str]:
        """Level2: 扫页面可交互元素, rapidfuzz 算相似度, top-K 验证."""
        try:
            from rapidfuzz import fuzz
        except ImportError:
            logger.warning("rapidfuzz not installed, skip Level2")
            return None
        semantic = element_data.get("semantic_info") or {}
        name = element_data.get("element_name") or ""
        sem_text = semantic.get("text") or ""
        # 构建候选目标列表 (元素名、语义文本各算一次, 避免拼接稀释相似度)
        targets = [t for t in [name, sem_text] if t]
        if not targets:
            return None
        candidates = []
        for sel in INTERACTIVE_SELECTORS:
            try:
                els = await page.query_selector_all(sel)
            except Exception:
                continue
            for el in els:
                try:
                    text = (await el.text_content() or "").strip()
                    aria = await el.get_attribute("aria-label") or ""
                    placeholder = await el.get_attribute("placeholder") or ""
                    for cand in [text, aria, placeholder]:
                        if not cand:
                            continue
                        # 取所有目标中的最高分
                        score = max(fuzz.ratio(t, cand) for t in targets)
                        if score >= FUZZ_SCORE_THRESHOLD:
                            candidates.append((score, el, cand))
                except Exception:
                    continue
        candidates.sort(key=lambda x: x[0], reverse=True)
        for score, el, cand in candidates[:FUZZ_TOP_K]:
            try:
                if await el.is_visible():
                    return await self._build_locator_from_candidate(el, cand)
            except Exception:
                continue
        return None

    async def _build_locator_from_candidate(self, el, cand_text: str) -> str:
        """从候选元素构造 Playwright 定位器 (优先 text)."""
        return f"page.get_by_text(\"{cand_text}\")"

    async def _heal_by_ai_dom(self, page, element_data: dict) -> Optional[str]:
        """Level3: DOM + 元素描述发 LLM, 返回定位器, 验证."""
        if self.gateway is None:
            return None
        try:
            dom = await page.content()
        except Exception as e:
            logger.warning(f"ai_dom content fetch failed: {e}")
            return None
        dom = (dom or "")[:DOM_TRUNCATE]
        semantic = element_data.get("semantic_info") or {}
        prompt = f"""页面 DOM 如下, 找到元素 "{element_data.get('element_name')}" 的 Playwright 定位器.
元素语义: {semantic}
只输出一个定位器字符串 (如 page.get_by_role("button", name="登录")), 不要解释.

DOM:
{dom}"""
        try:
            resp = await self.gateway.chat([{"role": "user", "content": prompt}])
        except Exception as e:
            logger.warning(f"ai_dom LLM call failed: {e}")
            return None
        locator = (resp.get("content") or "").strip()
        # 验证定位器有效
        try:
            loc = page.locator(locator)
            await loc.wait_for(state="visible", timeout=3000)
            return locator
        except Exception:
            return None

    async def _on_heal_success(self, element_data, locator, strategy) -> Optional[dict]:
        """返回 writeback 信号 (若有), 调用方执行 ElementService.writeback."""
        eid = element_data.get("element_id")
        if not eid:
            return None
        await self.element_cache.record_heal_success(eid, {"type": "healed", "value": locator, "strategy": strategy})
        if await self.element_cache.should_writeback_to_repo(eid):
            wb = await self.element_cache.get_writeback_locator(eid)
            if wb:
                return {"element_id": eid, "locator": wb}
        return None

    async def _on_heal_failure(self, element_data):
        eid = element_data.get("element_id")
        if eid:
            await self.element_cache.record_heal_failure(eid)
