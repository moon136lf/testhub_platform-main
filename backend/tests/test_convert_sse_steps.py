"""转换 SSE 逐步骤绑定明细测试（方案V1 阶段7）。

事件格式对齐现有 SSEStream.send_message（type/stage/content/progress/data），
新事件 type=step_binding / summary，前端按 type 分发。
"""
import pytest
from unittest.mock import MagicMock

from app.services.script_convert_service import ScriptConvertService


class FakeSSE:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kw):
        self.messages.append(kw)


@pytest.mark.asyncio
async def test_emit_step_binding_message_format():
    sse = FakeSSE()
    svc = ScriptConvertService(db=MagicMock(), gateway=MagicMock())
    await svc._emit_step_binding(
        sse, 2, "账号输入框", "L2", "请输入账号", "#zh", 0.82, matched=True)
    m = sse.messages[0]
    assert m["type"] == "step_binding"
    assert m["stage"] == "convert_script"
    assert "步骤2" in m["content"] and "L2" in m["content"] and "0.82" in m["content"]
    assert m["data"]["matched"] is True
    assert m["data"]["step"] == 2


@pytest.mark.asyncio
async def test_emit_step_binding_miss_message():
    sse = FakeSSE()
    svc = ScriptConvertService(db=MagicMock(), gateway=MagicMock())
    await svc._emit_step_binding(sse, 3, "神秘控件", "", "", "", None, matched=False)
    m = sse.messages[0]
    assert m["type"] == "step_binding"
    assert "步骤3" in m["content"] and "未命中" in m["content"]
    assert m["data"]["matched"] is False


@pytest.mark.asyncio
async def test_emit_summary_message():
    sse = FakeSSE()
    svc = ScriptConvertService(db=MagicMock(), gateway=MagicMock())
    await svc._emit_summary(sse, total=7, bound=6, pending=1)
    m = sse.messages[0]
    assert m["type"] == "summary"
    assert "6/7" in m["content"]
    assert m["data"] == {"total": 7, "bound": 6, "pending": 1}


@pytest.mark.asyncio
async def test_convert_one_emits_step_bindings_and_summary():
    """转换流程中 step3 循环逐条直播 + 循环后汇总。"""
    import asyncio

    class FakeGateway:
        def __init__(self):
            self.tokens = 0

        async def chat(self, messages, **kw):
            self.tokens += 50
            msg = messages[0]["content"]
            if "转成结构化动作意图" in msg:
                return {"content": '[{"step":1,"action":"fill","target":"用户名","value":"admin"},'
                                   '{"step":2,"action":"fill","target":"密码","value":"x"}]', "tokens": 50}
            if "转成断言计划" in msg:
                return {"content": '[]', "tokens": 50}
            if "生成 Python" in msg:
                return {"content": 'def test_login(page):\n    pass\n', "tokens": 50}
            return {"content": "{}", "tokens": 10}

    class FakeLookup:
        async def find_candidates(self, project_id, target, intent_action=None, page_id=None):
            if target == "用户名":
                return [{"element_id": "el-1", "element_name": "用户名", "locator": "#u",
                         "confidence": 5, "score": 1.0, "match_level": "L1"}]
            return []

    class FakeSession:
        async def execute(self, stmt):
            return self
        def scalar_one_or_none(self):
            return None
        def scalars(self):
            return self
        def all(self, *a, **kw):
            return []
        async def commit(self):
            pass
        async def flush(self):
            pass
        async def add(self, obj):
            pass

    sse = FakeSSE()
    svc = ScriptConvertService(db=FakeSession(), gateway=FakeGateway())
    case = {"id": "c1", "name": "登录", "project_id": "p1",
            "steps": [{"step": 1, "action": "输入用户名admin", "expected": ""},
                      {"step": 2, "action": "输入密码x", "expected": ""}],
            "expected_result": "进入首页"}
    await svc.convert_one(case, sse, lookup=FakeLookup(), ai_optimize=False)

    types = [m["type"] for m in sse.messages]
    assert types.count("step_binding") == 2
    bindings = [m for m in sse.messages if m["type"] == "step_binding"]
    assert bindings[0]["data"]["matched"] is True
    assert bindings[0]["data"]["level"] == "L1"  # match_level 透传修复
    assert bindings[1]["data"]["matched"] is False
    assert bindings[1]["data"]["level"] == ""
    summary = [m for m in sse.messages if m["type"] == "summary"]
    assert len(summary) == 1
    assert summary[0]["data"] == {"total": 2, "bound": 1, "pending": 1}
