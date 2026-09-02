# backend/tests/test_script_convert_service.py
"""Convert service orchestration tests (mock gateway + lookup + sse)."""
import asyncio
import pytest
from app.services.script_convert_service import ScriptConvertService, ConvertError


class FakeGateway:
    def __init__(self):
        self.tokens = 0
    async def chat(self, messages, **kw):
        self.tokens += 50
        msg = messages[0]["content"]
        if "转成结构化动作意图" in msg:
            return {"content": '[{"step":1,"action":"fill","target":"用户名","value":"admin"}]', "tokens": 50}
        if "转成断言计划" in msg:
            return {"content": '[{"step":1,"assertion_type":"status_changed","target":"页面","expected":"首页","is_valid":true}]', "tokens": 50}
        if "生成 Python" in msg:
            return {"content": 'def test_login(page):\n    page.get_by_label("用户名").fill("admin")\n', "tokens": 50}
        return {"content": "{}", "tokens": 10}


class FakeLookup:
    async def find(self, project_id, target):
        return 'page.get_by_label("用户名")' if target == "用户名" else None


class FakeSSE:
    def __init__(self):
        self.messages = []
    async def send_message(self, **kw):
        self.messages.append(kw)


class FakeSession:
    """内存 DB session stub。"""
    def __init__(self):
        self.scripts = []
        self.cases = {}
        self.sessions = []
    async def execute(self, stmt):
        return self  # 极简 stub
    def scalar_one_or_none(self):
        return None
    def scalars(self):
        return self  # select(ScriptAsset.name) 查重结果 stub: 空集合
    def all(self, *a, **kw):
        return []
    async def add(self, obj):
        if hasattr(obj, "case_id"):
            self.scripts.append(obj)
        else:
            self.sessions.append(obj)
    async def commit(self):
        pass
    async def flush(self):
        pass


def test_convert_single_case_writes_script():
    gw = FakeGateway()
    svc = ScriptConvertService(db=FakeSession(), gateway=gw)
    case = {
        "id": "c1", "name": "登录", "project_id": "p1",
        "steps": [{"step": 1, "action": "输入用户名admin", "expected": "输入成功"}],
        "expected_result": "进入首页",
    }
    sse = FakeSSE()
    script = asyncio.run(svc.convert_one(case, sse, lookup=FakeLookup(), ai_optimize=False))
    assert script.content.startswith("def test_login")
    assert script.locator_source == "element_library"
    assert script.step_mapping[0]["status"] == "ok"
    assert len(sse.messages) >= 3  # 开始/匹配/完成


def test_missing_steps_raises_convert_error():
    svc = ScriptConvertService(db=FakeSession(), gateway=FakeGateway())
    case = {"id": "c2", "name": "x", "steps": [], "expected_result": "y"}
    with pytest.raises(ConvertError):
        asyncio.run(svc.convert_one(case, FakeSSE(), lookup=FakeLookup(), ai_optimize=False))
