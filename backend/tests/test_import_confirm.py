"""
测试导入确认端点 POST /test-cases/import/confirm

- 重名自动后缀 (2)/(3)
- confirm 不调 LLM（AI 标准化已移至 preview 阶段），ai_optimize=True 也直接入库
- 无 AI 优化直接入库
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from app.main import app


def _make_client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def override_db(mock_db_session):
    from app.core.database import get_db
    app.dependency_overrides[get_db] = lambda: mock_db_session
    yield
    app.dependency_overrides.clear()


def _case_body(name="测试用例A", priority="P1"):
    return {
        "name": name, "priority": priority, "case_type": "functional",
        "steps": [{"step": 1, "action": "点击", "target": "按钮", "data": "", "expected": "待补"}],
        "expected_result": "成功",
    }


@pytest.fixture
def mock_db_session():
    """AsyncSession mock：查重返回 0，add/commit 无操作。"""
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=execute_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    yield session


AI_OK_RESPONSE = {
    "content": '{"name":"AI优化用例","priority":"P2","steps":[{"step":1,"action":"点击登录按钮","target":"登录按钮","data":"","expected":"跳转首页"}],"expected_result":"登录成功"}',
    "tokens": 100,
}


@pytest.mark.asyncio
async def test_confirm_basic_import(mock_db_session):
    async with _make_client() as client:
        resp = await client.post(
            "/api/v1/test-cases/import/confirm?project_id=00000000-0000-0000-0000-000000000001",
            json={"cases": [_case_body()], "ai_optimize": False})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["imported"] == 1
    assert data["failed"] == 0
    assert data["ai_ok_count"] == 0


@pytest.mark.asyncio
async def test_confirm_duplicate_name_auto_suffix(mock_db_session):
    """同批两条同名 + DB 已存在同名 → (2)/(3) 后缀。"""
    # 第一次查重返回 1（存在），之后返回 0
    results = []

    async def _exec(*a, **kw):
        r = MagicMock()
        r.scalar.return_value = 1 if len(results) == 0 else 0
        results.append(r)
        return r
    mock_db_session.execute = _exec

    async with _make_client() as client:
        resp = await client.post(
            "/api/v1/test-cases/import/confirm?project_id=00000000-0000-0000-0000-000000000001",
            json={"cases": [_case_body(name="X"), _case_body(name="X")], "ai_optimize": False})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["imported"] == 2
    # 验证保存的名字带后缀
    saved = []
    for call in mock_db_session.add.call_args_list:
        obj = call.args[0] if call.args else call.kwargs.get("case")
        if obj is not None and hasattr(obj, "name"):
            saved.append(obj.name)
    assert saved == ["X", "X (2)"]


@pytest.mark.asyncio
async def test_confirm_ignores_ai_optimize_flag(mock_db_session):
    """AI 标准化已移到 /import/preview 阶段；confirm 即使传 ai_optimize=True 也不调 LLM 直接入库。"""
    async with _make_client() as client:
        with patch("app.services.import_ai_optimizer.ai_gateway") as mock_gw:
            mock_gw.chat = AsyncMock(return_value=AI_OK_RESPONSE)
            resp = await client.post(
                "/api/v1/test-cases/import/confirm?project_id=00000000-0000-0000-0000-000000000001",
                json={"cases": [_case_body()], "ai_optimize": True})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["imported"] == 1
    mock_gw.chat.assert_not_called()  # 不应触发任何 LLM 调用
    saved = mock_db_session.add.call_args_list[-1].args[0]
    assert saved.name == "测试用例A"  # 原样入库，不做 AI 改写
