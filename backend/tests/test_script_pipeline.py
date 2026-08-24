"""Script pipeline unit tests (mock LLM)."""
import asyncio
import pytest
from typing import Optional
from app.services.script_pipeline import (
    step0_normalize,
    step1_to_actions,
    step2_to_assertions,
    step3_match_locators,
    step4_generate_code,
    ActionIntent,
    ActionWithLocator,
    AssertionPlan,
    ElementLookupProto,
    LLMGatewayProto,
    GenerateResult,
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


class FakeElementLookup:
    """内存元素库, page.element_name -> locator 字符串。"""
    def __init__(self, mapping: dict):
        self.mapping = mapping

    async def find(self, project_id: str, target: str) -> Optional[str]:
        # target 形如 "LoginPage.username" 或 "用户名"
        return self.mapping.get(target)


class TestStep3MatchLocators:
    def _actions(self):
        return [ActionIntent(step=1, action="fill", target="用户名", value="admin")]

    def test_all_matched(self):
        lk = FakeElementLookup({"用户名": "page.get_by_label('用户名')"})
        result = asyncio_run(step3_match_locators(self._actions(), "p1", lk, ai_optimize=False, gateway=None))
        assert result[0].locator == "page.get_by_label('用户名')"
        assert result[0].locator_status == "matched"
        assert result[0].locator_source == "element_library"

    def test_none_matched_draft(self):
        lk = FakeElementLookup({})
        result = asyncio_run(step3_match_locators(self._actions(), "p1", lk, ai_optimize=False, gateway=None))
        assert result[0].locator_status == "none_draft"
        assert result[0].locator is None
        assert result[0].locator_source == "none_draft"

    def test_partial_mixed(self):
        lk = FakeElementLookup({"用户名": "page.get_by_label('用户名')"})
        actions = [
            ActionIntent(step=1, action="fill", target="用户名", value="admin"),
            ActionIntent(step=2, action="click", target="登录按钮"),
        ]
        result = asyncio_run(step3_match_locators(actions, "p1", lk, ai_optimize=False, gateway=None))
        assert result[0].locator_source == "mixed"


class TestStep4GenerateCode:
    def _inputs(self):
        actions = [ActionWithLocator(step=1, action="fill", target="用户名",
                                     value="admin", locator='page.get_by_label("用户名")',
                                     locator_status="matched")]
        asserts = [AssertionPlan(step=1, assertion_type="status_changed",
                                 target="页面", expected="首页", is_valid=True)]
        case = NormalizedCase(case_id="c1", title="登录", steps=[], expected_result="进入首页")
        return case, actions, asserts

    def test_generates_script_and_mapping(self):
        gw = FakeGateway('import pytest\n\ndef test_login(page):\n    page.get_by_label("用户名").fill("admin")\n')
        case, actions, asserts = self._inputs()
        result = asyncio_run(step4_generate_code(case, actions, asserts, gw))
        assert isinstance(result, GenerateResult)
        assert "def test_login" in result.script
        assert len(result.step_mapping) == 1
        assert result.step_mapping[0]["status"] == "ok"

    def test_missing_locator_blocks_step(self):
        gw = FakeGateway('def test_x(page):\n    pass\n')
        case, actions, asserts = self._inputs()
        actions[0].locator = None
        actions[0].locator_status = "none_draft"
        result = asyncio_run(step4_generate_code(case, actions, asserts, gw))
        assert result.step_mapping[0]["status"] == "blocked"

