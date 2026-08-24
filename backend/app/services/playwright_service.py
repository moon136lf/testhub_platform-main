"""
Playwright Service for Element Extraction
"""

from playwright.async_api import async_playwright, Page, Browser, Playwright
from typing import Optional, Dict, List
import logging
import asyncio

# 复用核心定位器生成/验证/语义提取函数（Task 11 实现）
from app.services.playwright_locator_core import (
    generate_locators_for_element,
    verify_and_score_locator,
    extract_semantic_info,
    scan_interactive_elements,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PlaywrightService",
    "generate_locators_for_element",
    "verify_and_score_locator",
    "extract_semantic_info",
    "scan_interactive_elements",
]


class PlaywrightService:
    """Playwright 浏览器自动化服务"""

    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None

    async def start(self):
        """启动 Playwright 和浏览器"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled'
                ]
            )
            logger.info("Playwright browser started successfully")
        except Exception as e:
            logger.error(f"Failed to start Playwright: {e}")
            raise

    async def close(self):
        """关闭浏览器和 Playwright"""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("Playwright browser closed")
        except Exception as e:
            logger.error(f"Failed to close Playwright: {e}")

    async def fetch_page(
        self,
        url: str,
        username: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict:
        """
        抓取页面元素

        Args:
            url: 目标 URL
            username: 可选的登录用户名
            password: 可选的登录密码

        Returns:
            包含截图和元素列表的字典
        """
        page = await self.browser.new_page()

        try:
            # 设置视口大小
            await page.set_viewport_size({"width": 1920, "height": 1080})

            # 访问页面
            logger.info(f"Navigating to: {url}")
            await page.goto(url, timeout=30000, wait_until="networkidle")

            # 处理登录
            if username and password:
                await self._auto_login(page, username, password)

            # 等待页面稳定
            await asyncio.sleep(2)

            # 截图
            screenshot_bytes = await page.screenshot(full_page=True, type="png")
            logger.info("Page screenshot captured")

            # 提取元素
            elements = await self._extract_elements(page)
            logger.info(f"Extracted {len(elements)} elements")

            return {
                "screenshot": screenshot_bytes,
                "elements": elements,
                "url": page.url
            }

        except Exception as e:
            logger.error(f"Failed to fetch page: {e}")
            raise

        finally:
            await page.close()

    async def _auto_login(self, page: Page, username: str, password: str):
        """
        自动登录表单

        尝试识别并填充常见的登录表单
        """
        try:
            logger.info("Attempting auto-login...")

            # 查找用户名输入框
            username_selectors = [
                'input[type="text"]',
                'input[type="email"]',
                'input[name*="user"]',
                'input[name*="username"]',
                'input[name*="email"]',
                'input[placeholder*="用户"]',
                'input[placeholder*="邮箱"]',
                'input[id*="user"]'
            ]

            username_filled = False
            for selector in username_selectors:
                try:
                    await page.fill(selector, username, timeout=2000)
                    username_filled = True
                    logger.info(f"Username filled with selector: {selector}")
                    break
                except Exception:
                    continue

            # 查找密码输入框
            password_selectors = [
                'input[type="password"]',
                'input[name*="pass"]',
                'input[name*="pwd"]',
                'input[placeholder*="密码"]',
                'input[id*="pass"]'
            ]

            password_filled = False
            for selector in password_selectors:
                try:
                    await page.fill(selector, password, timeout=2000)
                    password_filled = True
                    logger.info(f"Password filled with selector: {selector}")
                    break
                except Exception:
                    continue

            if not (username_filled and password_filled):
                logger.warning("Could not find login form fields")
                return

            # 查找登录按钮
            login_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("登录")',
                'button:has-text("Login")',
                'button:has-text("Sign in")',
                'a:has-text("登录")',
                '[class*="login"][class*="button"]'
            ]

            for selector in login_selectors:
                try:
                    await page.click(selector, timeout=2000)
                    logger.info(f"Login button clicked: {selector}")
                    # 等待页面跳转
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    logger.info("Login successful")
                    return
                except Exception:
                    continue

            logger.warning("Could not find login button")

        except Exception as e:
            logger.error(f"Auto-login failed: {e}")
            # 登录失败不抛出异常，继续抓取当前页面

    async def _extract_elements(self, page: Page) -> List[Dict]:
        """
        提取页面可交互元素

        Returns:
            元素列表，每个元素包含类型、属性、坐标、定位策略等信息
        """
        elements = []

        # 可交互元素选择器
        selectors_map = {
            "button": "button",
            "input": "input:not([type='hidden'])",
            "link": "a[href]",
            "select": "select",
            "textarea": "textarea"
        }

        for elem_type, selector in selectors_map.items():
            try:
                locators = page.locator(selector)
                count = await locators.count()
                logger.debug(f"Found {count} {elem_type} elements")

                for i in range(min(count, 100)):  # 限制最多 100 个同类元素
                    elem = locators.nth(i)

                    try:
                        # 只抓取可见元素
                        if not await elem.is_visible(timeout=1000):
                            continue

                        # 获取边界框
                        box = await elem.bounding_box()
                        if not box:
                            continue

                        # 获取元素属性
                        element_data = {
                            "type": elem_type,
                            "id": await elem.get_attribute("id") or "",
                            "class": await elem.get_attribute("class") or "",
                            "name": await elem.get_attribute("name") or "",
                            "placeholder": await elem.get_attribute("placeholder") or "",
                            "value": await elem.get_attribute("value") or "",
                            "href": await elem.get_attribute("href") or "",
                            "coords": {
                                "x": int(box["x"]),
                                "y": int(box["y"]),
                                "width": int(box["width"]),
                                "height": int(box["height"])
                            }
                        }

                        # 获取文本内容
                        try:
                            text = await elem.text_content(timeout=1000)
                            element_data["text"] = (text or "").strip()[:100]
                        except:
                            element_data["text"] = ""

                        # 生成定位策略链
                        element_data["locator_chain"] = self._generate_locator_chain(element_data)

                        elements.append(element_data)

                    except Exception as e:
                        logger.debug(f"Failed to extract {elem_type} element {i}: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Failed to extract {elem_type} elements: {e}")
                continue

        return elements

    def _generate_locator_chain(self, elem_data: Dict) -> Dict:
        """
        生成 5 种定位策略

        优先级: id > css > role > text > xpath
        """
        strategies = []
        priority = 1

        # 1. ID 定位
        if elem_data.get("id"):
            strategies.append({
                "type": "id",
                "value": f"#{elem_data['id']}",
                "priority": priority
            })
            priority += 1

        # 2. CSS 定位 (class)
        if elem_data.get("class"):
            classes = elem_data["class"].split()
            if classes:
                first_class = classes[0]
                strategies.append({
                    "type": "css",
                    "value": f".{first_class}",
                    "priority": priority
                })
                priority += 1

        # 3. Role 定位 (ARIA)
        role_map = {
            "button": "button",
            "input": "textbox",
            "link": "link",
            "select": "combobox",
            "textarea": "textbox"
        }
        if elem_data["type"] in role_map:
            strategies.append({
                "type": "role",
                "value": role_map[elem_data["type"]],
                "priority": priority
            })
            priority += 1

        # 4. Text 定位
        if elem_data.get("text") and len(elem_data["text"]) > 0:
            strategies.append({
                "type": "text",
                "value": elem_data["text"][:50],
                "priority": priority
            })
            priority += 1

        # 5. XPath 定位 (兜底)
        xpath = f"//{elem_data['type']}"
        if elem_data.get("id"):
            xpath += f"[@id='{elem_data['id']}']"
        elif elem_data.get("name"):
            xpath += f"[@name='{elem_data['name']}']"
        elif elem_data.get("class"):
            first_class = elem_data["class"].split()[0]
            xpath += f"[contains(@class, '{first_class}')]"

        strategies.append({
            "type": "xpath",
            "value": xpath,
            "priority": priority
        })

        return {"strategies": strategies}
