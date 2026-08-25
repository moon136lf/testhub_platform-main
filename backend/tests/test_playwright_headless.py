"""playwright_service.start headless/timeout 参数化测试 (不启动真实浏览器)."""
import inspect
from app.services.playwright_service import PlaywrightService


class TestStartParams:
    def test_start_accepts_headless_param(self):
        sig = inspect.signature(PlaywrightService.start)
        assert "headless" in sig.parameters
        assert sig.parameters["headless"].default is True
        assert "timeout" in sig.parameters

    def test_start_default_headless_true(self):
        # 元素抓取路径不传参 → 默认 headless=True，零回归
        sig = inspect.signature(PlaywrightService.start)
        assert sig.parameters["headless"].default is True
