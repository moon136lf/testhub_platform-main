"""自愈引擎 Level1-4 状态机 (#5b).

Level1 semantic (复用 SmartLocator 逻辑) → Level2 rapidfuzz DOM 模糊 → Level3 AI DOM (LLM)
→ Level4 视觉 (kimi2.6 多模态).
每级命中: record_heal_success + confidence+1 + 检查回写; 失败: record_heal_failure + 降级.
全失败抛 ElementNotFoundError. 透明接入 SmartLocator.

定位器契约: 各级返回**选择器字符串** (CSS/XPath/text=/role= 引擎语法, 如 'text="登录"'),
与主路径 locator_strategies 的 value 格式一致, 可直接传 page.locator() 解析.
禁止返回 page.get_by_*(...) Python API 表达式 (page.locator() 不认, 真实浏览器会抛错).
"""
import logging
import re
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

# Level4 视觉: 截图最大宽度 (超过则缩放, 控制 base64 体积/token 成本; 审查 #6)
VISUAL_MAX_WIDTH = 1280

# LLM 定位器提示词后缀: 要求输出选择器字符串 (非 page.get_by_* 表达式)
LOCATOR_OUTPUT_INSTRUCTION = (
    "只输出一个 Playwright 选择器字符串 (如 role=button[name=\"登录\"] 或 text=\"登录\" "
    "或 #id 或 [data-testid='x']), 不要输出 page.get_by_role(...) 等 Python API 表达式, "
    "不要解释, 不要 markdown 代码块."
)


class SelfHealEngine:
    """自愈引擎 Level1-4."""

    def __init__(self, gateway, element_cache):
        self.gateway = gateway
        self.element_cache = element_cache

    async def heal(self, page, element_data: dict, action: str, **kw) -> dict:
        """逐级自愈, 返回 {success, locator, strategy, heal_log, writeback}.

        heal_log 条目含命中定位器 (locator) — 审查 #8: 增强 ExecutionDetail.heal_log 诊断价值;
        timestamp 无法取 (无时钟注入), 略 (spec §8 允许).
        """
        heal_log = []
        # Level1: semantic
        loc = await self._heal_by_semantic(page, element_data)
        heal_log.append({"level": 1, "strategy": "semantic", "success": loc is not None, "locator": loc})
        if loc:
            wb = await self._on_heal_success(element_data, loc, "semantic")
            return {"success": True, "locator": loc, "strategy": "semantic", "heal_log": heal_log, "writeback": wb}
        # Level2: dom_fuzz
        loc = await self._heal_by_dom_fuzz(page, element_data)
        heal_log.append({"level": 2, "strategy": "dom_fuzz", "success": loc is not None, "locator": loc})
        if loc:
            wb = await self._on_heal_success(element_data, loc, "dom_fuzz")
            return {"success": True, "locator": loc, "strategy": "dom_fuzz", "heal_log": heal_log, "writeback": wb}
        # Level3: ai_dom
        loc = await self._heal_by_ai_dom(page, element_data)
        heal_log.append({"level": 3, "strategy": "ai_dom", "success": loc is not None, "locator": loc})
        if loc:
            wb = await self._on_heal_success(element_data, loc, "ai_dom")
            return {"success": True, "locator": loc, "strategy": "ai_dom", "heal_log": heal_log, "writeback": wb}
        # Level4: visual (kimi2.6 多模态)
        loc = await self._heal_by_visual(page, element_data)
        heal_log.append({"level": 4, "strategy": "visual", "success": loc is not None, "locator": loc})
        if loc:
            wb = await self._on_heal_success(element_data, loc, "visual")
            return {"success": True, "locator": loc, "strategy": "visual", "heal_log": heal_log, "writeback": wb}
        # 全失败
        await self._on_heal_failure(element_data)
        return {"success": False, "locator": None, "strategy": None, "heal_log": heal_log, "writeback": None}

    async def _heal_by_semantic(self, page, element_data: dict) -> Optional[str]:
        """Level1: 复用 SmartLocator semantic 自愈逻辑 (text/aria/role 候选)."""
        from app.services.smart_locator import SmartLocator
        sl = SmartLocator(element_data)
        return await sl._heal_by_semantic(page)

    async def _heal_by_dom_fuzz(self, page, element_data: dict) -> Optional[str]:
        """Level2: 扫页面可交互元素, rapidfuzz 算相似度, top-K 验证.

        候选按命中属性 (text/aria-label/placeholder) 构造对应选择器, 保证 page.locator() 可解析.
        """
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
                    for field, cand in [("text", text), ("aria", aria), ("placeholder", placeholder)]:
                        if not cand:
                            continue
                        # 取所有目标中的最高分
                        score = max(fuzz.ratio(t, cand) for t in targets)
                        if score >= FUZZ_SCORE_THRESHOLD:
                            candidates.append((score, el, field, cand))
                except Exception:
                    continue
        candidates.sort(key=lambda x: x[0], reverse=True)
        for score, el, field, cand in candidates[:FUZZ_TOP_K]:
            try:
                if await el.is_visible():
                    return self._build_locator_from_candidate(field, cand)
            except Exception:
                continue
        return None

    @staticmethod
    def _build_locator_from_candidate(field: str, cand_text: str) -> str:
        """从候选元素构造选择器字符串 (按命中属性选形式, 全部是 page.locator() 可解析的选择器)."""
        if field == "aria":
            return f"[aria-label=\"{cand_text}\"]"
        if field == "placeholder":
            return f"[placeholder=\"{cand_text}\"]"
        return f"text=\"{cand_text}\""

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
{LOCATOR_OUTPUT_INSTRUCTION}

DOM:
{dom}"""
        try:
            resp = await self.gateway.chat([{"role": "user", "content": prompt}])
        except Exception as e:
            logger.warning(f"ai_dom LLM call failed: {e}")
            return None
        locator = self._clean_llm_locator(resp.get("content"))
        if not locator:
            return None
        # 验证定位器有效
        try:
            loc = page.locator(locator)
            await loc.wait_for(state="visible", timeout=3000)
            return locator
        except Exception:
            return None

    async def _heal_by_visual(self, page, element_data: dict) -> Optional[str]:
        """Level4: 截图发 kimi2.6 多模态 (provider=moonshot), LLM 看图返回定位器, 验证.

        路线1: Level4 专用 kimi2.6 (显式 provider="moonshot"), 其他级仍默认 glm5.2.
        """
        if self.gateway is None:
            return None
        try:
            screenshot = await page.screenshot()
        except Exception as e:
            logger.warning(f"visual screenshot failed: {e}")
            return None
        if not screenshot:
            return None
        img_b64 = self._screenshot_to_b64(screenshot)
        if not img_b64:
            return None
        semantic = element_data.get("semantic_info") or {}
        prompt_text = (
            f"页面截图如下, 找到元素 \"{element_data.get('element_name')}\" 的 Playwright 定位器.\n"
            f"元素语义: {semantic}\n"
            f"{LOCATOR_OUTPUT_INSTRUCTION}"
        )
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ]}
        ]
        try:
            # 显式 provider="moonshot" (路线1: Level4 专用 kimi2.6, 其他仍默认)
            resp = await self.gateway.chat(messages, provider="moonshot")
        except Exception as e:
            logger.warning(f"visual LLM call failed: {e}")
            return None
        locator = self._clean_llm_locator(resp.get("content"))
        if not locator:
            return None
        # 验证定位器有效
        try:
            loc = page.locator(locator)
            await loc.wait_for(state="visible", timeout=3000)
            return locator
        except Exception:
            return None

    # 匹配 page.get_by_*(...) Python API 表达式 (审查 Critical #1: page.locator() 不认)
    _GET_BY_EXPR_RE = re.compile(r"page\.(get_by_\w+)\(", re.IGNORECASE)
    # 提取类似定位器的子串: 优先围栏/引号内内容, 兜底取含定位器语法特征的一段
    _LOCATOR_LIKE_RE = re.compile(
        r"(text=\"[^\"]+\"|text='[^']+'"
        r"|[a-zA-Z-]+:has-text\([^)]+\)"
        r"|\[aria-label=\"[^\"]+\"\]|\[placeholder=\"[^\"]+\"\]|\[data-testid=['\"][^'\"]+['\"]\]"
        r"|role=\w+\[[^\]]+\]"
        r"|#[\w-]+"
        r"|xpath=[^\"'\s]+"
        r"|(?:html|head|body|div|span|button|a|input|select|textarea|form|label|table|ul|li)(?:\.[\w-]+|\[[^\]]+\]|:[\w-]+(?:\([^)]*\))?)*)"
    )

    @classmethod
    def _clean_llm_locator(cls, raw: Optional[str]) -> Optional[str]:
        """清洗 LLM 返回的定位器输出.

        处理: markdown 代码围栏 / 前后杂讯 (如"定位器是：") / 首尾引号反引号;
        拒绝 page.get_by_*(...) Python API 表达式 (返回 None, 交由降级链).
        """
        if not raw:
            return None
        text = raw.strip()
        # 去 markdown 围栏: 取 ``` 围栏内内容 (若有)
        fence = re.search(r"```[a-zA-Z0-9]*\s*\n?(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        # 拒绝 Python API 表达式 (如 page.get_by_role(...)) — page.locator() 无法解析
        if cls._GET_BY_EXPR_RE.search(text):
            return None
        # 优先从原文提取定位器子串 (引号闭合以原文为准); 提取不到再按整段处理
        m = cls._LOCATOR_LIKE_RE.search(text)
        if m:
            return m.group(0)
        # 整段处理: 去常见前缀杂讯 ("定位器是："/"Locator:" 等) + 首尾成对引号/反引号
        first_line = text.splitlines()[0].strip() if text.splitlines() else ""
        cleaned = re.sub(r"^(定位器|选择器|locator|selector)\s*[是为:：=]\s*", "", first_line, flags=re.IGNORECASE).strip()
        cleaned = cleaned.strip("`\"'“”‘’")
        return cleaned or None

    @staticmethod
    def _screenshot_to_b64(screenshot: bytes) -> Optional[str]:
        """截图 → base64. 超宽截图先缩放 (审查 #6: 控制多模态 token 成本), 失败降级原图."""
        import base64
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(screenshot))
            if img.width > VISUAL_MAX_WIDTH:
                ratio = VISUAL_MAX_WIDTH / img.width
                img = img.resize((VISUAL_MAX_WIDTH, max(int(img.height * ratio), 1)))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            return base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            # PIL 缺失/图片异常 → 原样 base64 (PNG), 保证可用性
            logger.warning(f"screenshot compress skipped: {e}")
            return base64.b64encode(screenshot).decode()

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
