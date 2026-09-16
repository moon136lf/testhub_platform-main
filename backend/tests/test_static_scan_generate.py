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

    def test_parse_leading_text_with_fenced_json(self):
        out = [{"index": 0, "strategies": [{"type": "id", "value": "#x", "priority": 1}]}]
        text = f"好的，以下是结果：\n```json\n{json.dumps(out)}\n```"
        assert StaticScanService.parse_ai_output(text) == out

    def test_parse_leading_text_with_bare_json(self):
        out = [{"index": 0, "strategies": [{"type": "id", "value": "#x", "priority": 1}]}]
        text = f"分析如下：\n{json.dumps(out)}\n希望有帮助"
        assert StaticScanService.parse_ai_output(text) == out


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

    def test_truncated_snippet_attr_change_no_reuse(self):
        """缺陷2：元素属性变化在 snippet 截断点之后，元素摘要 hash 仍须识别变化→重生成"""
        svc = StaticScanService(gateway=MagicMock())
        comp = _comp()
        # 首次：input 元素 id=old_user，snippet 超 4000 字符被截断
        comp["elements"] = [{"tag": "input", "text": None, "v_model": "form.user",
                             "placeholder": None, "id": "old_user", "href": None,
                             "name": None, "data_testid": None, "pos": 900}]
        comp["template_snippet"] = "<div>" + "x" * 4000 + "<input id='old_user' v-model='form.user'></div>"
        h1 = StaticScanService.compute_component_hash(comp)
        # 属性变化（id 改名）在截断点之后，snippet 相同部分不变
        comp["elements"] = [{"tag": "input", "text": None, "v_model": "form.user",
                             "placeholder": None, "id": "new_user", "href": None,
                             "name": None, "data_testid": None, "pos": 900}]
        h2 = StaticScanService.compute_component_hash(comp)
        assert h1 != h2
        # decide_reuse：旧 hash → 不复用
        old = {"src/views/Cases.vue": {"content_hash": h1,
              "strategies_by_index": {0: {"strategies": [{"type": "id", "value": "#old_user", "priority": 1}]}}}}
        assert svc.decide_reuse(comp, old) is None

    def test_hash_stable_when_nothing_changed(self):
        svc = StaticScanService(gateway=MagicMock())
        comp = _comp()
        h1 = StaticScanService.compute_component_hash(comp)
        h2 = StaticScanService.compute_component_hash(_comp())
        assert h1 == h2
