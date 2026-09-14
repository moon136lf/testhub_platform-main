"""需求②：识别验证码拆两步（captcha_recognize + fill），不再合并 input_captcha。"""
import asyncio
import pytest

from app.services.script_pipeline import step1_to_actions, NormalizedCase, VALID_ACTIONS
from app.services.step_codegen import generate_script, SUPPORTED_ACTIONS


class FakeGateway:
    def __init__(self, content):
        self._content = content

    async def chat(self, messages, **kw):
        return {"content": self._content, "tokens": 10}


class TestPipelineTwoStep:
    def _case(self):
        return NormalizedCase(
            case_id="c1", title="登录",
            steps=[
                {"step": 3, "action": "识别验证码", "target": "图形验证码图片",
                 "expected": "识别出验证码"},
                {"step": 4, "action": "输入", "target": "验证码输入框",
                 "data": "识别结果", "expected": "输入框显示识别出的验证码"},
            ],
            expected_result="进入首页",
        )

    def test_two_steps_convert_to_two_intents(self):
        gw = FakeGateway(
            '[{"step":3,"action":"captcha_recognize","target":"#captcha-img","value":""},'
            '{"step":4,"action":"fill","target":"#captcha-input","value":"识别结果"}]'
        )
        actions = asyncio.run(step1_to_actions(self._case(), gw))
        assert len(actions) == 2
        assert actions[0].action == "captcha_recognize"
        assert actions[0].target == "#captcha-img"
        assert actions[1].action == "fill"
        assert actions[1].target == "#captcha-input"

    def test_captcha_recognize_is_valid_action(self):
        assert "captcha_recognize" in VALID_ACTIONS

    def test_prompt_no_longer_merges_captcha(self):
        from app.services.script_pipeline import STEP1_PROMPT
        assert "input_captcha" not in STEP1_PROMPT
        assert "captcha_recognize" in STEP1_PROMPT
        assert "不得再出现单独的输入验证码" not in STEP1_PROMPT


class TestCodegenCaptchaRecognize:
    def test_supported(self):
        assert "captcha_recognize" in SUPPORTED_ACTIONS

    def test_generates_recognize_without_fill(self):
        code = generate_script("t", [
            {"seq": 1, "action": "captcha_recognize", "target": "#captcha-img",
             "value": "", "expected": ""},
        ])
        assert "captcha_text = _recognize_captcha(" in code
        assert "#captcha-img" in code
        assert ".fill(" not in code

    def test_requires_target(self):
        with pytest.raises(ValueError):
            generate_script("t", [
                {"seq": 1, "action": "captcha_recognize", "target": "",
                 "value": "", "expected": ""},
            ])


class TestInputCaptchaCompat:
    def test_old_action_still_supported(self):
        from app.services.step_codegen import generate_script as gs
        code = gs("t", [
            {"seq": 1, "action": "input_captcha", "target": "#captcha-input",
             "value": "", "extra_target": "#captcha-img", "expected": ""},
        ])
        assert "_recognize_captcha" in code and "#captcha-img" in code
