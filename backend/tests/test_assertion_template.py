"""断言推断确定性模板库测试（方案V1 阶段6，Robot Framework 词表思路）。"""
import pytest
from app.services.script_pipeline import infer_assertion_rule, step2_to_assertions, step0_normalize


def test_expect_value_from_display():
    # "显示test02" + 测试数据 test02 → expect_value
    a = infer_assertion_rule("账号输入框", "test02", "显示test02", "input")
    assert a is not None and a["assertion_type"] == "expect_value"
    assert a["expected"] == "test02"


def test_navigate_empty_value_returns_none():
    """navigate 但 value 不是 URL → None 走 LLM 兜底，不生成必败 URL 断言。"""
    assert infer_assertion_rule("浏览器地址栏", "", "进入登录页", "navigate") is None
    assert infer_assertion_rule("浏览器地址栏", "进入登录页", "跳转到登录页", "click") is None


def test_target_passed_through():
    """target 参数透传到结果；传 None 则结果 target 为 None。"""
    a = infer_assertion_rule(None, "test02", "显示test02", "input")
    assert a is not None and a["target"] is None
    b = infer_assertion_rule("密码输入框", "123456", "显示为密文", "input")
    assert b["target"] == "密码输入框"


def test_expect_url_from_navigate():
    a = infer_assertion_rule("浏览器地址栏", "http://x/login", "进入登录页", "navigate")
    assert a["assertion_type"] == "expect_url"
    assert a["expected"] == "login"  # 从数据 URL 提取 path 尾段


def test_expect_attribute_password():
    a = infer_assertion_rule("密码输入框", "123456", "显示为密文", "input")
    assert a["assertion_type"] == "expect_attribute"
    assert a["expected"] == "password"


def test_expect_toast_from_success_word():
    a = infer_assertion_rule("登录按钮", "", "欢迎登陆，提示成功", "click")
    assert a["assertion_type"] in ("expect_toast", "expect_text")


def test_uninferable_returns_none():
    assert infer_assertion_rule("某按钮", "", "触发某种效果", "click") is None


@pytest.mark.asyncio
async def test_step2_rule_hit_skips_llm():
    """规则命中的行不再调 LLM；未命中行走 LLM 兜底。"""
    calls = {"n": 0}

    class FakeGateway:
        async def chat(self, messages, **kw):
            calls["n"] += 1
            return {"content": '[{"step": 2, "assertion_type": "ambiguous", "target": "", "expected": "触发某种效果", "is_valid": false}]', "tokens": 1}

    case = step0_normalize({
        "id": "c1", "name": "登录",
        "steps": [
            {"step": 1, "action": "输入test02到账号输入框", "value": "test02", "expected": "显示test02"},
            {"step": 2, "action": "点击某按钮", "expected": "触发某种效果"},
        ],
        "expected_result": "登录成功",
    })
    plans = await step2_to_assertions(case, FakeGateway())
    assert calls["n"] == 1  # 仅未命中的 step2 走了 LLM
    by_step = {p.step: p for p in plans}
    assert by_step[1].assertion_type == "expect_value"
    assert by_step[1].expected == "test02"
    assert by_step[2].assertion_type == "ambiguous" and not by_step[2].is_valid
