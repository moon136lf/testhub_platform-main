"""Script pipeline unit tests (mock LLM)."""
import asyncio
import pytest
from app.services.script_pipeline import (
    step0_normalize,
    step1_to_actions,
    step2_to_assertions,
    ActionIntent,
    AssertionPlan,
    LLMGatewayProto,
    NormalizeError,
    NormalizedCase,
)


def asyncio_run(coro):
    return asyncio.run(coro)


class FakeGateway:
    """内存 LLM 网关, 返回预设 JSON。"""
    def __init__(self, response_text: str):
        self._response = response_text
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        return {"content": self._response, "tokens": 100}


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


class TestStep1ToActions:
    def _case(self):
        return NormalizedCase(
            case_id="c1", title="登录",
            steps=[{"step": 1, "action": "输入用户名admin", "expected": "输入成功"}],
            expected_result="进入首页",
        )

    def test_parses_actions(self):
        gw = FakeGateway('[{"step":1,"action":"fill","target":"用户名","value":"admin"}]')
        actions = asyncio_run(step1_to_actions(self._case(), gw))
        assert len(actions) == 1
        assert actions[0].action == "fill"
        assert actions[0].value == "admin"

    def test_invalid_action_rejected(self):
        gw = FakeGateway('[{"step":1,"action":"bogus","target":"x"}]')
        with pytest.raises(ValueError):
            asyncio_run(step1_to_actions(self._case(), gw))


class TestStep2ToAssertions:
    def _case(self):
        return NormalizedCase(
            case_id="c1", title="登录",
            steps=[{"step": 1, "action": "点击登录", "expected": "跳转首页"}],
            expected_result="成功进入首页",
        )

    def test_parses_assertions(self):
        gw = FakeGateway('[{"step":1,"assertion_type":"status_changed","target":"页面","expected":"首页","is_valid":true}]')
        asserts = asyncio_run(step2_to_assertions(self._case(), gw))
        assert asserts[0].assertion_type == "status_changed"
        assert asserts[0].is_valid is True

    def test_tautological_assertion_marked_invalid(self):
        gw = FakeGateway('[{"step":1,"assertion_type":"row_visible","target":"按钮","expected":"可见","is_valid":true}]')
        # row_visible of a button = tautological per blacklist -> forced invalid
        asserts = asyncio_run(step2_to_assertions(self._case(), gw))
        assert asserts[0].is_valid is False
