"""codegen 扩词表测试（方案V1 阶段5）：input_captcha/assert_url/assert_attribute。"""
import pytest
from app.services.step_codegen import generate_script, SUPPORTED_ACTIONS


def test_input_captcha_uses_extra_element():
    code = generate_script("t", [
        {"seq": 1, "action": "input_captcha", "target": "#captcha-input",
         "value": "", "element_name": "验证码输入框",
         "extra_target": "#captcha-img", "expected": ""},
    ])
    assert "recognize" in code or "captcha" in code
    assert "#captcha-input" in code and "#captcha-img" in code


def test_assert_url_contains():
    code = generate_script("t", [
        {"seq": 1, "action": "assert_url", "target": "", "value": "", "expected": "/login"},
    ])
    assert "page.url" in code and "/login" in code


def test_assert_attribute_password():
    code = generate_script("t", [
        {"seq": 2, "action": "assert_attribute", "target": "#pwd", "value": "type",
         "expected": "password"},
    ])
    assert 'get_attribute("type")' in code and "password" in code


def test_input_captcha_requires_extra_target():
    with pytest.raises(ValueError):
        generate_script("t", [
            {"seq": 1, "action": "input_captcha", "target": "#captcha-input",
             "value": "", "extra_target": "", "expected": ""},
        ])


def test_assert_url_requires_expected():
    with pytest.raises(ValueError):
        generate_script("t", [
            {"seq": 1, "action": "assert_url", "target": "", "value": "", "expected": ""},
        ])


def test_assert_attribute_requires_value():
    with pytest.raises(ValueError):
        generate_script("t", [
            {"seq": 1, "action": "assert_attribute", "target": "#pwd", "value": "",
             "expected": "password"},
        ])


def test_assert_attribute_requires_expected():
    with pytest.raises(ValueError):
        generate_script("t", [
            {"seq": 1, "action": "assert_attribute", "target": "#pwd", "value": "type",
             "expected": ""},
        ])


def test_unknown_action_still_raises():
    with pytest.raises(ValueError):
        generate_script("t", [{"seq": 1, "action": "no_such", "target": "", "value": ""}])
