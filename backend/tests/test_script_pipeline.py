"""Script pipeline unit tests (mock LLM)."""
import pytest
from app.services.script_pipeline import step0_normalize, NormalizeError, NormalizedCase


class TestStep0Normalize:
    def _case(self, **over):
        base = {
            "id": "c1", "name": "登录-正常登录", "steps": [
                {"step": 1, "action": "输入用户名admin", "expected": "输入成功"},
                {"step": 2, "action": "点击登录", "expected": "跳转首页"},
            ],
            "expected_result": "成功进入首页",
        }
        base.update(over)
        return base

    def test_normalize_ok(self):
        nc = step0_normalize(self._case())
        assert isinstance(nc, NormalizedCase)
        assert nc.title == "登录-正常登录"
        assert len(nc.steps) == 2
        assert nc.expected_result == "成功进入首页"

    def test_empty_steps_blocks(self):
        with pytest.raises(NormalizeError):
            step0_normalize(self._case(steps=[]))

    def test_empty_expected_blocks(self):
        with pytest.raises(NormalizeError):
            step0_normalize(self._case(expected_result=""))

    def test_missing_title_uses_step_summary(self):
        nc = step0_normalize(self._case(name=""))
        assert nc.title != ""  # generated from steps
