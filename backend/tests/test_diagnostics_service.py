"""Diagnostics (#5c) service tests (mock db/gateway/storage)."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock


def asyncio_run(coro): return asyncio.run(coro)


class TestAiDiagnosisList:
    def test_dict_wrapped_to_array(self):
        """#4 旧格式（单对象 dict）读取 → 包装为单元素数组不崩."""
        from app.models.test_case import ScriptAsset
        sa = ScriptAsset(id="s1", case_id="c1", project_id="p1", name="x",
                         content="code", version=1, status="confirmed",
                         ai_diagnosis={"mode": "rule", "category": "script_problem"})
        assert sa.diagnosis_list == [{"mode": "rule", "category": "script_problem"}]

    def test_list_passthrough_and_none(self):
        from app.models.test_case import ScriptAsset
        sa = ScriptAsset(id="s1", case_id="c1", project_id="p1", name="x",
                         content="code", version=1, status="confirmed",
                         ai_diagnosis=[{"mode": "rule"}, {"mode": "multimodal"}])
        assert len(sa.diagnosis_list) == 2
        sa2 = ScriptAsset(id="s2", case_id="c1", project_id="p1", name="y",
                          content="code", version=1, status="confirmed",
                          ai_diagnosis=None)
        assert sa2.diagnosis_list == []

    def test_append_diagnosis_card(self):
        """append 统一入口: 规则卡补 mode+created_at, 数组化存回."""
        from app.models.test_case import ScriptAsset
        sa = ScriptAsset(id="s1", case_id="c1", project_id="p1", name="x",
                         content="code", version=1, status="confirmed",
                         ai_diagnosis={"category": "page_bug"})  # 旧 dict
        card = {"category": "script_problem", "diagnosis": "定位器失效"}
        sa.append_diagnosis(card, mode="multimodal")
        assert len(sa.ai_diagnosis) == 2
        assert sa.ai_diagnosis[0]["mode"] == "rule"  # 旧 dict 被补 mode
        assert sa.ai_diagnosis[1]["mode"] == "multimodal"
        assert "created_at" in sa.ai_diagnosis[1]


# ---- T2: DiagnosticsService.analyze ----
from unittest.mock import patch

from app.services.diagnostics_service import DiagnosticsService


class FakeDB:
    def __init__(self, results):
        self._results = results  # 顺序弹出
        self.added = []

    async def execute(self, q):
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(side_effect=self._pop)
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(side_effect=self._pop)))
        return r

    def _pop(self):
        return self._results.pop(0) if self._results else None

    async def flush(self): pass
    async def commit(self): pass


def _make_detail(**kw):
    from app.models.execution import ExecutionDetail
    base = dict(execution_record_id="er1", script_id="s1", step=3, action="click",
                status="fail", error_type="locate_failed", error_msg="Element not found: #login-btn",
                stack_trace="Traceback...", screenshot_url="fail_step3.png",
                dom_snapshot="<html><button id='new-login-btn'>登录</button></html>",
                heal_status="failed", heal_log=[])
    base.update(kw)
    return ExecutionDetail(**base)


def _make_asset(**kw):
    from app.models.test_case import ScriptAsset
    base = dict(id="s1", case_id="c1", project_id="p1", name="登录脚本",
                content="await page.click('#login-btn')", version=1, status="confirmed",
                step_mapping=[{"step": 3, "case_req": "点击登录", "impl": "#login-btn",
                               "status": "blocked", "element_name": "登录按钮",
                               "page_name": "LoginPage", "action": "click", "value": ""}])
    base.update(kw)
    return ScriptAsset(**base)


class TestAnalyzeFetch:
    def test_analyze_happy_path(self):
        """execution_id+step 取数 → 拼 fragment → LLM → 卡 append + 契约字段齐."""
        from uuid import UUID
        detail = _make_detail()
        asset = _make_asset()
        # _get_fail_detail 两次 scalar_one_or_none (查 record → 查 detail), 再查 asset
        db = FakeDB([MagicMock(id=UUID(int=1)), detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={
            "content": '{"diagnosis": "定位器失效, ID 已变更为 new-login-btn", '
                       '"suggestion": "更新定位器为 #new-login-btn", '
                       '"new_locator": "#new-login-btn", "confidence": 0.92}',
            "tokens": 350,
        })
        storage = MagicMock()
        storage.get_object_bytes = MagicMock(return_value=b"fake-png")
        svc = DiagnosticsService(db=db, gateway=gw, storage=storage)
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        # §9.2.5 契约字段
        assert result["diagnosis"] == "定位器失效, ID 已变更为 new-login-btn"
        assert result["suggestion"] == "更新定位器为 #new-login-btn"
        assert result["new_locator"] == "#new-login-btn"
        assert result["confidence"] == 0.92
        assert result["apply_url"] == "/api/v1/diagnostics/apply"
        # LLM 调用参数: moonshot 多模态 + 埋点
        kwargs = gw.chat.call_args.kwargs
        assert kwargs.get("provider") == "moonshot"
        assert kwargs.get("stage") == "diagnosis"
        assert kwargs.get("project_id") == "p1"
        messages = gw.chat.call_args.args[0]
        content = messages[0]["content"]
        assert content[1]["type"] == "image_url"  # 多模态
        # prompt 含四要素
        prompt_text = content[0]["text"]
        assert "locate_failed" in prompt_text
        assert "click" in prompt_text and "#login-btn" in prompt_text  # fragment
        assert "Traceback" in prompt_text
        assert "<html>" in prompt_text
        # 诊断卡 append 到 asset.ai_diagnosis
        assert len(asset.ai_diagnosis) == 1
        assert asset.ai_diagnosis[0]["mode"] == "multimodal"
        assert asset.ai_diagnosis[0]["confidence"] == 0.92

    def test_analyze_no_step_takes_first_fail(self):
        """step=None → 取第一个 fail detail (FakeDB 顺序即查询顺序)."""
        detail = _make_detail()
        asset = _make_asset()
        from uuid import UUID
        db = FakeDB([MagicMock(id=UUID(int=1)), detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": '{"diagnosis": "d", "suggestion": "s", "new_locator": null, "confidence": null}', "tokens": 10})
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        result = asyncio_run(svc.analyze("exec-abc12345"))
        assert result["diagnosis"] == "d"
        assert result["new_locator"] is None

    def test_analyze_detail_not_found(self):
        db = FakeDB([None])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        try:
            asyncio_run(svc.analyze("exec-missing"))
            assert False, "should raise"
        except ValueError as e:
            assert "失败记录" in str(e) or "not found" in str(e).lower()

    def test_analyze_no_fail_detail(self):
        db = FakeDB([None])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        try:
            asyncio_run(svc.analyze("exec-x"))
            assert False, "should raise"
        except ValueError:
            pass

    def test_analyze_llm_invalid_json_falls_back(self):
        """LLM 输出非 JSON → 降级纯文本 diagnosis, new_locator/confidence=None."""
        detail = _make_detail()
        asset = _make_asset()
        from uuid import UUID
        db = FakeDB([MagicMock(id=UUID(int=1)), detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "页面按钮 ID 变了，建议改为 #new-login-btn", "tokens": 80})
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        assert "页面按钮" in result["diagnosis"]
        assert result["new_locator"] is None
        assert result["confidence"] is None

    def test_analyze_llm_getby_locator_rejected(self):
        """LLM 违约返回 get_by_* 表达式 → 清洗拒绝 → new_locator=None (防幻觉)."""
        detail = _make_detail()
        asset = _make_asset()
        from uuid import UUID
        db = FakeDB([MagicMock(id=UUID(int=1)), detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={
            "content": '{"diagnosis": "d", "suggestion": "s", '
                       '"new_locator": "page.get_by_role(\\"button\\", name=\\"登录\\")", "confidence": 0.8}',
            "tokens": 100,
        })
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        assert result["new_locator"] is None
        assert "无效" in result["suggestion"] or "手动" in result["suggestion"]

    def test_analyze_screenshot_missing_degrades(self):
        """截图文件读取失败 → 无图纯文本诊断（不崩）."""
        detail = _make_detail()
        asset = _make_asset()
        from uuid import UUID
        db = FakeDB([MagicMock(id=UUID(int=1)), detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": '{"diagnosis": "d", "suggestion": "s", "new_locator": "#x", "confidence": 0.7}', "tokens": 60})
        storage = MagicMock()
        storage.get_object_bytes = MagicMock(side_effect=Exception("object missing"))
        svc = DiagnosticsService(db=db, gateway=gw, storage=storage)
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        assert result["new_locator"] == "#x"
        # messages 无 image_url (纯文本)
        messages = gw.chat.call_args.args[0]
        assert messages[0]["content"][0]["type"] == "text"
        assert len(messages[0]["content"]) == 1

    def test_analyze_no_step_mapping_fragment_falls_back_to_content(self):
        """无 step_mapping → script_fragment 降级为整段脚本."""
        detail = _make_detail()
        asset = _make_asset(step_mapping=None)
        from uuid import UUID
        db = FakeDB([MagicMock(id=UUID(int=1)), detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": '{"diagnosis": "d", "suggestion": "s", "new_locator": null, "confidence": null}', "tokens": 10})
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        asyncio_run(svc.analyze("exec-abc12345", step=3))
        prompt_text = gw.chat.call_args.args[0][0]["content"][0]["text"]
        assert "await page.click" in prompt_text  # 整段脚本


# ---- T7: card.element_name ----
class TestAnalyzeCardExtras:
    def test_card_carries_element_name(self):
        """apply 需要 element_name — 诊断卡从 step_mapping 推并携带."""
        detail = _make_detail()
        asset = _make_asset()  # step_mapping[step=3].element_name = "登录按钮"
        from uuid import UUID
        db = FakeDB([MagicMock(id=UUID(int=1)), detail, asset])
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": '{"diagnosis": "d", "suggestion": "s", "new_locator": "#x", "confidence": 0.8}', "tokens": 50})
        svc = DiagnosticsService(db=db, gateway=gw, storage=MagicMock())
        result = asyncio_run(svc.analyze("exec-abc12345", step=3))
        assert result["card"]["element_name"] == "登录按钮"


# ---- T3: apply ----
# 注意: ElementService.find_by_name 内部先 uuid.UUID(project_id) 再查库,
# project_id 必须是合法 UUID 字符串 (与 T4 API 测试用例一致), 否则未到 FakeDB 即抛错.
_T3_PID = "1a2b3c4d-5e6f-4948-8276-000000000000"


class TestApply:
    def _element(self):
        from app.models.element import ElementRepository
        return ElementRepository(
            page_id="pg1", project_id=_T3_PID, element_id="login-btn",
            element_name="登录按钮", element_type="button",
            locator_strategies={"strategies": [{"type": "css", "value": "#old-btn"}]},
            source="manual", confidence=3)

    def test_apply_writes_element_with_ai_fixed(self):
        """apply: 清洗合法 → find_by_name → 回写 source=ai_fixed + confidence=round(c*10)."""
        el = self._element()
        db = FakeDB([el])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        result = asyncio_run(svc.apply(
            project_id=_T3_PID, element_name="登录按钮",
            new_locator="#new-login-btn", confidence=0.92))
        assert result["updated"] is True
        assert result["element_id"] == "login-btn"
        assert result["cleaned_locator"] == "#new-login-btn"
        assert el.source == "ai_fixed"
        assert el.confidence == 9  # round(0.92*10) = 9
        strategies = el.locator_strategies["strategies"]
        assert strategies[0]["value"] == "#new-login-btn"

    def test_apply_rejects_getby_expression(self):
        """get_by_* 表达式 → 400 语义 (ValueError), 不写库."""
        el = self._element()
        db = FakeDB([el])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        try:
            asyncio_run(svc.apply(project_id=_T3_PID, element_name="登录按钮",
                                  new_locator='page.get_by_role("button", name="登录")',
                                  confidence=0.9))
            assert False, "should raise"
        except ValueError as e:
            assert "无效" in str(e)

    def test_apply_element_not_found(self):
        db = FakeDB([None])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        try:
            asyncio_run(svc.apply(project_id=_T3_PID, element_name="不存在",
                                  new_locator="#x", confidence=0.9))
            assert False, "should raise"
        except ValueError as e:
            assert "未找到" in str(e)

    def test_apply_confidence_mapping_edge(self):
        """confidence=1.0 → 10."""
        el = self._element()
        db = FakeDB([el])
        svc = DiagnosticsService(db=db, gateway=MagicMock(), storage=MagicMock())
        asyncio_run(svc.apply(project_id=_T3_PID, element_name="登录按钮",
                              new_locator="text=\"登录\"", confidence=1.0))
        assert el.confidence == 10
