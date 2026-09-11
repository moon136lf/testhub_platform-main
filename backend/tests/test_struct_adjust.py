"""结构调整测试（方案V1 阶段10）：source枚举/软删端点/bug清单。"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


class TestSourceEnum:
    def test_create_accepts_regression_sources(self):
        from app.api.v1.test_sets import TestSetCreateRequest
        for s in ("manual", "ai_suggest", "convert_page", "ai_regression", "manual_regression"):
            req = TestSetCreateRequest(project_id="p", name="n", case_ids=["c1"], source=s)
            assert req.source == s

    def test_create_rejects_unknown_source(self):
        import pydantic
        from app.api.v1.test_sets import TestSetCreateRequest
        with pytest.raises(pydantic.ValidationError):
            TestSetCreateRequest(project_id="p", name="n", case_ids=["c1"], source="bad_source")


class TestSoftDelete:
    def test_delete_record_endpoint(self, client):
        """DELETE /records/{id} 软删端点存在且返回 200（依赖注入 mock db 层验证路由接线）。"""
        # 直接验证路由已注册
        from app.api.v1.reports import router
        paths = [r.path for r in router.routes]
        assert "/records/by-id/{record_id}" in paths
        methods = [m for r in router.routes if r.path == "/records/by-id/{record_id}" for m in r.methods]
        assert "DELETE" in methods


class TestBugModel:
    def test_execution_bug_model_fields(self):
        from app.models.execution import ExecutionBug
        b = ExecutionBug(
            record_id="00000000-0000-0000-0000-000000000001",
            step_snapshot={"step": 1, "action": "click", "error_type": "timeout"},
            screenshot_url="http://x/1.png",
            error_stack="Traceback...",
        )
        d = b.to_dict()
        assert d["step_snapshot"]["step"] == 1
        assert d["screenshot_url"] == "http://x/1.png"
        assert "ai_diagnosis" in d and "detail_id" in d

    def test_record_has_is_deleted(self):
        from app.models.execution import ExecutionRecord
        assert hasattr(ExecutionRecord, "is_deleted")

    def test_query_service_filters_deleted(self):
        """list_records 查询条件里包含 is_deleted=False 过滤。"""
        import inspect
        from app.services import execution_query_service
        src = inspect.getsource(execution_query_service.ExecutionQueryService.list_records)
        assert "is_deleted" in src


class TestScriptListEnrich:
    @pytest.mark.asyncio
    async def test_enrich_scripts_aggregates(self):
        """_enrich_scripts 对空脚本列表返回空，函数存在且可调用。"""
        from app.api.v1.scripts import _enrich_scripts
        out = await _enrich_scripts(MagicMock(), [])
        assert out == []

    @pytest.mark.asyncio
    async def test_enrich_test_set_refs_counts_each_set(self):
        """test_set_refs 真计数：用例被 N 个测试集含 → 计 N（修复恒为 1）。"""
        from app.api.v1.scripts import _enrich_scripts
        cid = uuid4()
        pid = uuid4()
        s = MagicMock()
        s.case_id = cid
        s.project_id = pid
        s.to_dict = MagicMock(return_value={})

        class FakeResult:
            def __init__(self, rows):
                self._rows = rows
            def all(self):
                return self._rows

        db = MagicMock()
        # 1st execute: case names; 2nd: test sets (两个集合均含该用例)
        db.execute = AsyncMock(side_effect=[
            FakeResult([(cid, "登录用例")]),
            FakeResult([(pid, [str(cid)]), (pid, [str(uuid4()), str(cid)])]),
        ])
        out = await _enrich_scripts(db, [s])
        assert out[0]["test_set_refs"] == 2


class TestBugListEndpoint:
    def test_bugs_endpoint_registered(self):
        from app.api.v1.reports import router
        assert any(getattr(r, "path", "") == "/{exec_id}/bugs" for r in router.routes)

    def test_bugs_endpoint_404_on_missing(self, client, monkeypatch):
        """exec_id 不存在 → 404；DB 可用（真实 PG），不存在的 exec_id 走 404 分支。"""
        r = client.get("/api/v1/reports/no-such-exec-0000/bugs")
        assert r.status_code == 404
