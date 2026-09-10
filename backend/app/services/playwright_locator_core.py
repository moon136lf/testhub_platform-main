"""
Playwright Service - 定位器生成、验证与语义信息提取核心逻辑 (Task 11)

本模块提供与 Playwright 页面/元素交互的核心函数：
- generate_locators_for_element: 为单个元素生成 8 种候选定位器
- verify_and_score_locator: 验证定位器并计算最终评分（唯一性加分/非唯一扣分/稳定性扣分）
- extract_semantic_info: 提取元素语义信息（坐标、上下文、aria 属性），用于自愈兜底
"""

from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


async def generate_locators_for_element(page, element) -> List[Dict[str, Any]]:
    """
    为单个元素生成多种候选定位器

    Args:
        page: Playwright Page 对象
        element: Playwright Locator 对象

    Returns:
        候选定位器列表，每项含 type/value/base_score
    """
    candidates: List[Dict[str, Any]] = []

    # 获取元素属性
    elem_id = await element.get_attribute("id")
    elem_name = await element.get_attribute("name")
    elem_class = await element.get_attribute("class")
    elem_testid = await element.get_attribute("data-testid")
    elem_type = await element.get_attribute("type")
    elem_role = await element.get_attribute("role")

    raw_text = await element.inner_text()
    elem_text = raw_text.strip()[:50] if raw_text else ""

    tag_name = await element.evaluate("el => el.tagName.toLowerCase()")

    # 策略 1: ID (最高优先级)
    if elem_id:
        candidates.append({
            "type": "id",
            "value": f"#{elem_id}",
            "base_score": 100,
        })

    # 策略 2: data-testid
    if elem_testid:
        candidates.append({
            "type": "data-testid",
            "value": f"[data-testid='{elem_testid}']",
            "base_score": 95,
        })

    # 策略 3: name
    if elem_name:
        candidates.append({
            "type": "name",
            "value": f"[name='{elem_name}']",
            "base_score": 90,
        })

    # 策略 4: role + text
    if elem_role and elem_text:
        candidates.append({
            "type": "role-text",
            "value": f"{tag_name}[role='{elem_role}']:has-text('{elem_text}')",
            "base_score": 85,
        })

    # 策略 5: text only
    if elem_text:
        candidates.append({
            "type": "text",
            "value": f"{tag_name}:has-text('{elem_text}')",
            "base_score": 80,
        })

    # 策略 6: class + type
    if elem_class and elem_type:
        first_class = elem_class.split()[0]
        candidates.append({
            "type": "class-type",
            "value": f"{tag_name}.{first_class}[type='{elem_type}']",
            "base_score": 70,
        })

    # 策略 7: CSS selector（基于 DOM 路径）
    css_selector = await element.evaluate("""
        el => {
            let path = [];
            while (el.parentElement) {
                let selector = el.tagName.toLowerCase();
                let siblings = Array.from(el.parentElement.children).filter(
                    e => e.tagName === el.tagName
                );
                if (siblings.length > 1) {
                    selector += `:nth-of-type(${siblings.indexOf(el) + 1})`;
                }
                path.unshift(selector);
                el = el.parentElement;
                if (path.length > 5) break;
            }
            return path.join(' > ');
        }
    """)
    candidates.append({
        "type": "css",
        "value": css_selector,
        "base_score": 50,
    })

    # 策略 8: XPath
    xpath = await element.evaluate("""
        el => {
            if (el.id) return `//*[@id="${el.id}"]`;
            let path = [];
            while (el.parentElement) {
                let siblings = Array.from(el.parentElement.children).filter(
                    e => e.tagName === el.tagName
                );
                let index = siblings.indexOf(el) + 1;
                path.unshift(`${el.tagName.toLowerCase()}[${index}]`);
                el = el.parentElement;
                if (path.length > 5) break;
            }
            return '/' + path.join('/');
        }
    """)
    candidates.append({
        "type": "xpath",
        "value": xpath,
        "base_score": 55,
    })

    # 策略 9: placeholder（输入框常用唯一标识；页面无 id/name 时是关键区分项）
    if elem_data_placeholder := await element.get_attribute("placeholder"):
        candidates.append({
            "type": "placeholder",
            "value": f"[placeholder='{elem_data_placeholder}']",
            "base_score": 88,
        })

    return candidates


async def verify_and_score_locator(page, locator_candidate: Dict[str, Any], target_element) -> Optional[Dict[str, Any]]:
    """
    验证定位器并计算最终评分

    Args:
        page: Playwright Page 对象
        locator_candidate: 候选定位器字典 {type, value, base_score}
        target_element: 目标元素 Locator

    Returns:
        验证后的定位器信息 {type, value, score, unique, verified}，失败返回 None
    """
    try:
        value = locator_candidate["value"]
        locator_type = locator_candidate["type"]

        # 使用定位器查找元素
        if locator_type == "xpath":
            found_elements = await page.locator(f"xpath={value}").all()
        else:
            found_elements = await page.locator(value).all()

        if len(found_elements) == 0:
            return None

        # 检查是否定位到目标元素
        # 注意: 把 Locator 直接作为 evaluate 参数传过去会变成 JS 值序列化,
        # el === target 恒为 False → 所有定位器验证失败 → 抓取 0 元素。
        # 必须先 evaluate_handle 拿到 ElementHandle 再做 DOM 身份比较。
        target_handle = await target_element.evaluate_handle("el => el")
        target_index = -1
        for i, elem in enumerate(found_elements):
            is_same = await elem.evaluate("(el, target) => el === target", target_handle)
            if is_same:
                target_index = i
                break

        if target_index < 0:
            return None

        # 消费方（执行引擎/自愈）都用 .first 取命中——非首个命中等于定位错元素。
        # 典型场景：目标页面 id 重复（两个 input 都叫 #inputCode），批量抓取第二个框时
        # `#inputCode` 命中的第一个不是它 → 该策略对该元素无效，剔除。
        if target_index != 0:
            logger.debug(
                f"Locator '{locator_candidate['value']}' matches target at index "
                f"{target_index} (not first) — discard for element-specific use"
            )
            return None

        # 计算最终评分
        score = locator_candidate["base_score"]

        # 唯一性加减分
        unique = len(found_elements) == 1
        if unique:
            score += 20
        else:
            # 非唯一但首个命中：执行时 .first 恰好对，但页面顺序变化即失效，重扣
            score -= 30

        # 稳定性扣分：nth-of-type/nth-child 只对"结构位置型"策略扣（css/xpath 全路径
        # 依赖位置，页面加个元素就失效）。但注意：对重复属性元素（页面 id 重复），
        # nth 路径是唯一能区分的手段，且路径唯一命中时 unique=True 已有加分，
        # 双重惩罚会把唯一可用策略压到阈值之下（点选补抓 404 的根因）。
        # 改为：nth 路径且唯一命中 → 不扣；nth 路径且非唯一 → 照扣。
        if ("nth-of-type" in value or "nth-child" in value) and not unique:
            score -= 15

        return {
            "type": locator_type,
            "value": value,
            "score": max(score, 0),
            "unique": unique,
            "verified": True,
        }

    except Exception as e:
        logger.debug(f"Verify locator failed for {locator_candidate.get('value')}: {e}")
        return None


async def extract_semantic_info(page, element) -> Dict[str, Any]:
    """
    提取元素语义信息（用于自愈兜底）

    Args:
        page: Playwright Page 对象
        element: Playwright Locator 对象

    Returns:
        语义信息字典 {type, text, placeholder, aria_label, aria_role, coords, context}
    """
    # 获取边界框
    box = await element.bounding_box()
    coords = {
        "x": int(box["x"]) if box else 0,
        "y": int(box["y"]) if box else 0,
        "width": int(box["width"]) if box else 0,
        "height": int(box["height"]) if box else 0,
    }

    # 获取父节点和兄弟节点
    parent_tag = await element.evaluate("el => el.parentElement?.tagName.toLowerCase()")
    sibling_tags = await element.evaluate("""
        el => Array.from(el.parentElement?.children || [])
            .map(e => e.tagName.toLowerCase())
    """)

    # 基本信息
    elem_type = await element.evaluate("el => el.tagName.toLowerCase()")
    # 归一化到语义类别 (与 models/element.py element_type 注释域一致: button/input/link/select/other)
    elem_type = {"a": "link"}.get(elem_type, elem_type)
    raw_text = await element.inner_text()
    elem_text = raw_text.strip()[:100] if raw_text else ""

    return {
        "type": elem_type,
        "text": elem_text,
        "placeholder": await element.get_attribute("placeholder"),
        "aria_label": await element.get_attribute("aria-label"),
        "aria_role": await element.get_attribute("role"),
        "coords": coords,
        "context": {
            "parent_tag": parent_tag,
            "sibling_tags": sibling_tags[:5] if sibling_tags else [],
        },
    }


# 可交互元素选择器清单（button/input/link/select/textarea + role/contenteditable/onclick）
INTERACTIVE_SELECTORS = [
    "button",
    "input:not([type='hidden'])",
    "textarea",
    "select",
    "a[href]",
    "[role='button']",
    "[role='link']",
    "[role='textbox']",
    "[contenteditable='true']",
    "[onclick]",
]


TEXT_SELECTORS = ["span", "p", "h1", "h2", "h3", "h4", "label", "td", "th"]


async def scan_interactive_elements(page, include_text: bool = False) -> List[Any]:
    """
    扫描页面上的可交互元素

    Args:
        page: Playwright Page 对象
        include_text: 同时扫描文字/不可点击元素（span/p/标题等），非空 inner_text 才保留

    Returns:
        可见的元素 Locator 列表（基于坐标去重，交互元素优先于文本元素）
    """
    elements: List[Any] = []
    seen_coords = set()  # 基于坐标去重

    async def scan_selectors(selectors, require_text: bool):
        for selector in selectors:
            try:
                found = await page.locator(selector).all()
                for elem in found:
                    try:
                        # 过滤不可见元素
                        if not await elem.is_visible():
                            continue

                        # 文本元素必须有非空 inner_text（过滤布局占位）
                        if require_text:
                            raw = await elem.inner_text()
                            if not raw.strip():
                                continue

                        # 坐标去重
                        box = await elem.bounding_box()
                        if box:
                            coord_key = (int(box["x"]), int(box["y"]))
                            if coord_key in seen_coords:
                                continue
                            seen_coords.add(coord_key)

                        elements.append(elem)
                    except Exception:
                        continue
            except Exception:
                continue

    await scan_selectors(INTERACTIVE_SELECTORS, require_text=False)
    if include_text:
        await scan_selectors(TEXT_SELECTORS, require_text=True)

    return elements


# elementFromPoint 命中后打标记，用专用属性选择器拿 Locator（避免元素句柄跨传输）
_PICK_MARKER_JS = """
([x, y]) => {
  const e = document.elementFromPoint(x, y);
  if (!e) return null;
  e.setAttribute('data-pick-hit', '1');
  return {tag: e.tagName.toLowerCase(), text: (e.innerText || '').slice(0, 100)};
}
"""

PICK_HIT_SELECTOR = "[data-pick-hit='1']"


# node-info 面包屑 JS：elementFromPoint → 清除旧 data-pick-hit 标记 → 打新标记 →
# 沿 parentElement 上溯 8 层构建祖先链（每层含 tag/id/class/文本摘要/css_path/index_in_parent）
_NODE_CHAIN_JS = """
([x, y]) => {
  const e = document.elementFromPoint(x, y);
  if (!e) return null;
  document.querySelectorAll('[data-pick-hit]').forEach(n => n.removeAttribute('data-pick-hit'));
  e.setAttribute('data-pick-hit', '1');
  const chain = [];
  let cur = e;
  let depth = 0;
  while (cur && cur.tagName && depth < 8) {
    const tag = cur.tagName.toLowerCase();
    const parent = cur.parentElement;
    let seg = tag;
    if (parent) {
      const same = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
      if (same.length > 1) seg += `:nth-of-type(${same.indexOf(cur) + 1})`;
    }
    let css = seg;
    if (cur.id) css = tag + '#' + cur.id;
    let p2 = parent;
    while (p2) {
      const ptag = p2.tagName.toLowerCase();
      let pseg = ptag;
      if (p2.id) { css = ptag + '#' + p2.id + ' > ' + css; break; }
      const gp = p2.parentElement;
      if (gp) {
        const same2 = Array.from(gp.children).filter(c => c.tagName === p2.tagName);
        if (same2.length > 1) pseg += `:nth-of-type(${same2.indexOf(p2) + 1})`;
      }
      css = pseg + ' > ' + css;
      p2 = gp;
      if (css.startsWith('html')) break;
    }
    chain.push({
      tag: tag,
      id: cur.id || null,
      cls: (cur.className || '').toString().slice(0, 60) || null,
      text: (cur.innerText || '').trim().slice(0, 50) || null,
      css_path: css,
      index_in_parent: parent ? Array.from(parent.children).indexOf(cur) : 0,
    });
    cur = parent;
    depth++;
  }
  return chain;
}
"""


async def _pipeline_for_locator(page, locator) -> Optional[Dict[str, Any]]:
    """
    定位器流水线共用 helper：generate → verify/score 过滤 → semantic 提取。

    Returns:
        同 element_tasks 阶段5 的 element dict 组装所需的三元组
        (hit_tag_or_None 不在此处, verified_locators, semantic)；失败抛异常由调用方处理。
    """
    from app.tasks.element_tasks import MIN_LOCATOR_SCORE

    candidates = await generate_locators_for_element(page, locator)
    verified_locators = []
    for candidate in candidates:
        verified = await verify_and_score_locator(page, candidate, locator)
        if verified and verified["score"] >= MIN_LOCATOR_SCORE:
            verified_locators.append(verified)
    semantic = await extract_semantic_info(page, locator)
    verified_locators.sort(key=lambda c: c["score"], reverse=True)
    return verified_locators, semantic


async def _node_locators_via_css(page, css_path: str) -> Optional[Dict[str, Any]]:
    """
    按 CSS 路径对节点重跑定位器流水线（面包屑切层级/同级切换用）。

    Returns:
        与 _pick_element_via_dom 同构的元素 dict；节点不存在或流水线失败返回 None。
    """
    import uuid as _uuid

    try:
        locator = page.locator(css_path).first
        if not await locator.count():
            return None
        verified_locators, semantic = await _pipeline_for_locator(page, locator)
        if not verified_locators:
            return None
    except Exception as e:
        logger.debug(f"node-locators pipeline failed for {css_path}: {e}")
        return None

    tag = await locator.evaluate("el => el.tagName.toLowerCase()")
    return {
        "temp_id": f"elem_pick_{_uuid.uuid4().hex[:8]}",
        "element_type": semantic["type"],
        "element_text": semantic["text"],
        "locator_strategies": {"strategies": verified_locators},
        "semantic_info": semantic,
        "position_x": semantic["coords"]["x"],
        "position_y": semantic["coords"]["y"],
        "width": semantic["coords"]["width"],
        "height": semantic["coords"]["height"],
        "attributes": {"pick_tag": tag} or None,
    }


async def _pick_element_via_dom(page, x: float, y: float) -> Optional[Dict[str, Any]]:
    """
    点选补抓：按坐标 elementFromPoint 命中元素 → 生成并验证定位器 → 提取语义。

    Returns:
        与 element_tasks 阶段5 产物同构的元素 dict；未命中返回 None。
    """
    from app.tasks.element_tasks import MIN_LOCATOR_SCORE  # noqa: F401 (pipeline helper 用)
    import uuid as _uuid

    hit = await page.evaluate(_PICK_MARKER_JS, [x, y])
    if not hit:
        logger.warning(f"pick-element: elementFromPoint miss at ({x}, {y})")
        return None

    try:
        locator = page.locator(PICK_HIT_SELECTOR).first
        try:
            verified_locators, semantic = await _pipeline_for_locator(page, locator)
        finally:
            # 无论成败都移除标记，避免污染后续扫描
            # 注意: Locator 作为 evaluate 参数会被序列化为 undefined（P2 教训同源），
            # 必须用选择器字符串让 JS 自己找元素
            await page.evaluate(
                "sel => { const el = document.querySelector(sel);"
                " if (el) el.removeAttribute('data-pick-hit'); }",
                PICK_HIT_SELECTOR,
            )
    except Exception as e:
        logger.warning(
            f"pick-element pipeline failed at ({x}, {y}) tag={hit.get('tag')} "
            f"text={hit.get('text', '')[:30]}: {type(e).__name__}: {e}"
        )
        return None
    if not verified_locators:
        logger.warning(
            f"pick-element: no locator scored >= threshold for tag={hit.get('tag')} "
            f"text={hit.get('text', '')[:30]} at ({x}, {y})"
        )
        return None

    return {
        "temp_id": f"elem_pick_{_uuid.uuid4().hex[:8]}",
        "element_type": semantic["type"],
        "element_text": semantic["text"],
        "locator_strategies": {"strategies": verified_locators},
        "semantic_info": semantic,
        "position_x": semantic["coords"]["x"],
        "position_y": semantic["coords"]["y"],
        "width": semantic["coords"]["width"],
        "height": semantic["coords"]["height"],
        "attributes": {"pick_tag": hit.get("tag")} or None,
    }
