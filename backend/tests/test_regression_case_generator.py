"""RegressionCaseGenerator tests (mock AIGateway + db; prompts asserted)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

from app.services.regression_case_generator import RegressionCaseGenerator, FORBIDDEN_WORDS


CASE_JSON = {
    "name": "REG-SQLI_断言参数化查询修复后查询正常",
    "priority": "P0",
    "precondition": "测试环境就绪，账户 test_${uuid} 已创建",
    "steps": [
        {"step": 1, "action": "input", "target": "搜索框", "data": "1' OR '1'='1",
         "expected": "输入被接受"},
        {"step": 2, "action": "click", "target": "查询按钮", "data": "",
         "expected": "接口返回 200 且无 SQL 错误"},
        {"step": 3, "action": "assert", "target": "结果列表", "data": "",
         "expected": "列表为空且 HTTP 状态 200"},
    ],
    "expected_result": "注入输入被参数化查询拦截，接口返回 200",
    "source_issue_id": "11111111-1111-1111-1111-111111111111",
}


def _mock_gateway_with(case_json):
    gw = MagicMock()
    gw.chat = AsyncMock(return_value={"content": json.dumps(case_json, ensure_ascii=False),
                                      "tokens": 300})
    return gw


class TestGenerateCase:
    @pytest.mark.asyncio
    async def test_generate_parses_case_and_strips_source(self):
        gw = _mock_gateway_with(CASE_JSON)
        gen = RegressionCaseGenerator(gw)
        result = await gen.generate_case(
            issue={"id": str(uuid4()), "title": "SQLi", "file_path": "a.py",
                   "line_no": 1, "description": "d", "example_code": "c", "severity": "high"},
            ai_suggestion={"suggestion": "param query", "fixed_code": "x", "original_code": "y"},
        )
        assert result["name"].startswith("REG-")
        assert "source_issue_id" not in result  # caller sets association
        assert isinstance(result["steps"], list) and len(result["steps"]) == 3

    @pytest.mark.asyncio
    async def test_prompt_contains_5_rules_and_forbidden_words(self):
        gw = _mock_gateway_with(CASE_JSON)
        gen = RegressionCaseGenerator(gw)
        await gen.generate_case(issue={"id": "x", "title": "t", "file_path": "f",
                                       "line_no": 1, "description": "", "example_code": "",
                                       "severity": "high"},
                                ai_suggestion={})
        sent = gw.chat.call_args[0][0]
        prompt_text = str(sent)
        for kw in ["代码依赖", "新旧路径", "幂等", "断言", "异常"]:
            assert kw in prompt_text
        for w in FORBIDDEN_WORDS:
            assert w in prompt_text  # forbidden words must be instructed away

    @pytest.mark.asyncio
    async def test_bad_json_raises(self):
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "junk", "tokens": 1})
        gen = RegressionCaseGenerator(gw)
        with pytest.raises(ValueError):
            await gen.generate_case(issue={"id": "x", "title": "t", "file_path": "f",
                                           "line_no": 1, "description": "", "example_code": "",
                                           "severity": "high"},
                                    ai_suggestion={})

    @pytest.mark.asyncio
    async def test_forbidden_word_in_output_rejected(self):
        """Review I5: prompt alone is not enforcement — the validator must
        reject cases whose name/action/expected contains a forbidden word."""
        bad_case = dict(CASE_JSON)
        bad_case["name"] = "REG-X_验证某功能正常"
        gw = _mock_gateway_with(bad_case)
        gen = RegressionCaseGenerator(gw)
        with pytest.raises(ValueError, match="forbidden word"):
            await gen.generate_case(issue={"id": "x", "title": "t", "file_path": "f",
                                           "line_no": 1, "description": "", "example_code": "",
                                           "severity": "high"},
                                    ai_suggestion={})

    @pytest.mark.asyncio
    async def test_invalid_step_action_rejected(self):
        """Review I5: action whitelist enforced post-LLM (non-Chinese junk verb
        hits the whitelist; forbidden-word check catches Chinese soft-asserts
        first — both paths guarded)."""
        bad_case = json.loads(json.dumps(CASE_JSON))
        bad_case["steps"][0]["action"] = "teleport"  # not in whitelist
        gw = _mock_gateway_with(bad_case)
        gen = RegressionCaseGenerator(gw)
        with pytest.raises(ValueError, match="not in allowed verbs"):
            await gen.generate_case(issue={"id": "x", "title": "t", "file_path": "f",
                                           "line_no": 1, "description": "", "example_code": "",
                                           "severity": "high"},
                                    ai_suggestion={})

    @pytest.mark.asyncio
    async def test_project_id_forwarded_to_gateway(self):
        """Review I7: generate_case must pass project_id to gateway.chat so
        token usage lands in ai_call_log."""
        gw = _mock_gateway_with(CASE_JSON)
        gen = RegressionCaseGenerator(gw)
        await gen.generate_case(issue={"id": "x", "title": "t", "file_path": "f",
                                       "line_no": 1, "description": "", "example_code": "",
                                       "severity": "high"},
                                ai_suggestion={}, project_id="proj-123")
        kwargs = gw.chat.call_args[1]
        assert kwargs.get("project_id") == "proj-123"
        assert kwargs.get("stage") == "whitescan_regression_case"


class TestBatchGenerate:
    @pytest.mark.asyncio
    async def test_incremental_skips_existing(self):
        gw = _mock_gateway_with(CASE_JSON)
        gen = RegressionCaseGenerator(gw)

        async def fake_exists(project_id, issue_id):
            return issue_id == "exists"

        gen._case_exists = fake_exists
        issues = [{"id": "exists"}, {"id": "new-1"}]
        results = await gen.batch_generate("pid", issues)
        assert results["generated_count"] == 1
        assert results["skipped_count"] == 1
