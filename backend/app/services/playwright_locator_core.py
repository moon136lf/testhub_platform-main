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
        target_found = False
        for elem in found_elements:
            is_same = await elem.evaluate("(el, target) => el === target", target_handle)
            if is_same:
                target_found = True
                break

        if not target_found:
            return None

        # 计算最终评分
        score = locator_candidate["base_score"]

        # 唯一性加减分
        if len(found_elements) == 1:
            score += 20
        else:
            score -= 10

        # 稳定性扣分（含 nth-of-type/nth-child 的定位器不稳定）
        if "nth-of-type" in value or "nth-child" in value:
            score -= 15

        return {
            "type": locator_type,
            "value": value,
            "score": max(score, 0),
            "unique": len(found_elements) == 1,
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


async def scan_interactive_elements(page) -> List[Any]:
    """
    扫描页面上的可交互元素

    Args:
        page: Playwright Page 对象

    Returns:
        可见的可交互元素 Locator 列表（基于坐标去重）
    """
    elements: List[Any] = []
    seen_coords = set()  # 基于坐标去重

    for selector in INTERACTIVE_SELECTORS:
        try:
            found = await page.locator(selector).all()
            for elem in found:
                try:
                    # 过滤不可见元素
                    if not await elem.is_visible():
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

    return elements
