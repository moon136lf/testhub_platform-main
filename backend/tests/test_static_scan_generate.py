"""AI 定位器生成：prompt构建/JSON解析/失败重试/hash增量决策"""
import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.services.static_scan_service import StaticScanService, PROMPT_TEMPLATE


def _comp(elements=1):
    els = [{"tag": "el-button", "text": "新建用例", "v_model": None, "placeholder": None,
            "id": None, "href": None, "name": None, "data_testid": None, "pos": 2}] * elements
    return {"file_path": "src/views/Cases.vue", "component_name": "Cases",
            "template_snippet": "<div><el-button>新建用例</el-button></div>",
            "content_hash": "h1", "elements": els}


class TestPrompt:
    def test_prompt_contains_snippet_and_element_list(self):
        prompt = StaticScanService.build_prompt(_comp())
        assert "新建用例" in prompt
        assert "el-button" in prompt
        assert "sibling-label" in prompt  # 新策略类型提示
        assert "JSON" in prompt


class TestParse:
    def test_parse_plain_json(self):
        out = [{"index": 0, "strategies": [{"type": "css", "value": ".el-button", "priority": 1}]}]
        assert StaticScanService.parse_ai_output(json.dumps(out)) == out

    def test_parse_json_fenced(self):
        out = [{"index": 0, "strategies": [{"type": "id", "value": "#x", "priority": 1}]}]
        fenced = f"```json\n{json.dumps(out)}\n```"
        assert StaticScanService.parse_ai_output(fenced) == out

    def test_parse_garbage_returns_none(self):
        assert StaticScanService.parse_ai_output("不是JSON") is None


class TestGenerateComponent:
    @pytest.mark.asyncio
    async def test_success(self):
        gw = MagicMock()
        out = [{"index": 0, "strategies": [{"type": "sibling-label", "value": "//label[.]/following-sibling::input", "priority": 1}]}]
        gw.chat = AsyncMock(return_value={"content": json.dumps(out), "tokens": 100})
        svc = StaticScanService(gateway=gw)
        result = await svc.generate_component(_comp())
        assert result["ai_failed"] is False
        assert result["elements"][0]["locator_strategies"]["strategies"][0]["type"] == "sibling-label"
        # provider 是 glm（历史遗留 key，实际 glm-5.2）
        gw.chat.assert_awaited_once()
        assert gw.chat.await_args.kwargs.get("provider") == "glm-2.5" or gw.chat.await_args.args[1] == "glm-2.5"

    @pytest.mark.asyncio
    async def test_retry_then_fail(self):
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "垃圾输出", "tokens": 10})
        svc = StaticScanService(gateway=gw)
        result = await svc.generate_component(_comp())
        assert result["ai_failed"] is True
        assert gw.chat.await_count == 2  # 重试1次
        assert all("locator_strategies" not in e for e in result["elements"])

    @pytest.mark.asyncio
    async def test_gateway_exception_marks_failed(self):
        gw = MagicMock()
        gw.chat = AsyncMock(side_effect=RuntimeError("api down"))
        svc = StaticScanService(gateway=gw)
        result = await svc.generate_component(_comp())
        assert result["ai_failed"] is True


class TestReuseDecision:
    def test_unchanged_hash_reuses(self):
        svc = StaticScanService(gateway=MagicMock())
        old = {"src/views/Cases.vue": {"content_hash": "h1",
              "strategies_by_index": {0: {"strategies": [{"type": "id", "value": "#a", "priority": 1}]}}}}
        comp = _comp()
        decision = svc.decide_reuse(comp, old)
        assert decision is not None and decision["reused"] is True
        assert comp["elements"][0]["locator_strategies"] == {"strategies": [{"type": "id", "value": "#a", "priority": 1}]}

    def test_changed_hash_regenerates(self):
        svc = StaticScanService(gateway=MagicMock())
        old = {"src/views/Cases.vue": {"content_hash": "OLD", "strategies_by_index": {}}}
        assert svc.decide_reuse(_comp(), old) is None

    def test_no_prior_record(self):
        svc = StaticScanService(gateway=MagicMock())
        assert svc.decide_reuse(_comp(), {}) is None
