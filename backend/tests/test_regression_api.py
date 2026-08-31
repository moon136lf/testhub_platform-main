"""Regression API tests (mock service / mock task)."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


PID = str(uuid4())
SID = str(uuid4())
UUID1 = "0f0e0d0c-0b0a-4948-8276-000000000001"
UUID2 = "0f0e0d0c-0b0a-4948-8276-000000000002"


class TestRegressionEndpoints:
    def test_list_returns_items(self):
        from app.api.v1 import regression as reg_mod

        async def fake_list(self, project_id, category=None, keyword=None):
            return [{"script": {"id": SID, "name": "登录"}, "ai_suggested": True,
                     "ai_reason": "P0核心用例", "actual_included": True,
                     "include_source": "ai"}]

        with patch.object(reg_mod.RegressionService, "list_view", fake_list):
            client = _client()
            resp = client.get(f"/api/v1/regression/list?project_id={PID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"][0]["actual_included"] is True

    def test_members_add(self):
        from app.api.v1 import regression as reg_mod

        with patch.object(reg_mod.RegressionService, "set_member", AsyncMock()):
            client = _client()
            resp = client.post("/api/v1/regression/members", json={
                "project_id": PID, "script_ids": [SID], "action": "add"})
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] == 1

    def test_identify_counts(self):
        from app.api.v1 import regression as reg_mod

        async def fake_identify(self, project_id):
            return {"identified": 8, "suggested_count": 5}

        with patch.object(reg_mod.RegressionService, "identify_project", fake_identify):
            client = _client()
            resp = client.post("/api/v1/regression/identify", json={"project_id": PID})
        assert resp.json()["data"]["suggested_count"] == 5

    def test_stats_shape(self):
        from app.api.v1 import regression as reg_mod

        async def fake_stats(self, project_id):
            return {"total": 8, "passed": 7, "failed": 1, "pass_rate": 87.5}

        with patch.object(reg_mod.RegressionService, "get_stats", fake_stats):
            client = _client()
            resp = client.get(f"/api/v1/regression/stats?project_id={PID}")
        assert resp.json()["data"]["pass_rate"] == 87.5

    def test_run_reuses_task_with_ui_regression(self):
        """REG-04: run 调 run_scripts_task, exec_type=ui_regression + fail_fast 进 config."""
        from app.api.v1 import regression as reg_mod

        async def fake_list(self, project_id, category=None, keyword=None):
            return [{"script": {"id": SID, "name": "s1"}, "ai_suggested": True,
                     "ai_reason": None, "actual_included": True, "include_source": "ai"},
                    {"script": {"id": str(uuid4()), "name": "s2"}, "ai_suggested": False,
                     "ai_reason": None, "actual_included": False, "include_source": None}]

        with patch.object(reg_mod.RegressionService, "list_view", fake_list), \
             patch.object(reg_mod.run_scripts_task, "delay") as delay:
            client = _client()
            resp = client.post("/api/v1/regression/run", json={
                "project_id": PID,
                "config": {"headless": True, "timeout": 60, "max_failures": 8,
                           "fail_fast": True}})
        assert resp.status_code == 200
        kwargs = delay.call_args.kwargs
        assert kwargs.get("exec_type") == "ui_regression"
        assert kwargs.get("config", {}).get("fail_fast") is True
        # 只取 included=true 的脚本
        assert kwargs.get("script_ids") == [SID]

    def test_run_empty_regression_400(self):
        from app.api.v1 import regression as reg_mod

        async def fake_list(self, project_id, category=None, keyword=None):
            return []

        with patch.object(reg_mod.RegressionService, "list_view", fake_list):
            client = _client()
            resp = client.post("/api/v1/regression/run", json={"project_id": PID})
        assert resp.status_code == 400

    def test_latest_execution(self):
        from app.api.v1 import regression as reg_mod

        async def fake_latest(self, script_id):
            return {"detail": {"id": "d1", "status": "fail"},
                    "record": {"exec_id": "exec-abc", "status": "fail"}}

        with patch.object(reg_mod.RegressionService, "latest_execution", fake_latest):
            client = _client()
            resp = client.get(f"/api/v1/regression/latest-execution?script_id={SID}")
        assert resp.json()["data"]["record"]["exec_id"] == "exec-abc"

    def test_push_calls_notifier(self):
        from app.api.v1 import regression as reg_mod

        with patch("app.services.notifier.notify_report_ready", AsyncMock()) as nr:
            client = _client()
            resp = client.post(f"/api/v1/regression/{UUID1}/push")
        assert resp.json()["data"]["pushed"] is True
        nr.assert_awaited_once()

    def test_report_summary(self):
        from app.api.v1 import regression as reg_mod

        async def fake_summary(self, project_id):
            return {"record": {"exec_id": "exec-x", "passed_count": 7, "fail_count": 1},
                    "failed_details": [{"id": str(uuid4()), "step": 3,
                                        "script_id": SID, "error_type": "locate_failed"}]}

        with patch.object(reg_mod.RegressionService, "report_summary", fake_summary):
            client = _client()
            resp = client.get(f"/api/v1/regression/report-summary?project_id={PID}")
        assert resp.json()["data"]["failed_details"][0]["script_id"] == SID


class TestScriptsListIncludeRegression:
    """GET /api/v1/scripts include_regression (模块 #8 T6)."""

    @pytest.mark.asyncio
    async def test_list_without_param_unchanged(self):
        """include_regression 缺省 → item 不含回归字段 (零破坏)."""
        from app.api.v1.scripts import list_scripts

        mock_script = MagicMock()
        mock_script.to_dict = MagicMock(return_value={"id": "s1", "name": "a.py"})
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[mock_script]))
        )
        db = MagicMock()
        db.execute = AsyncMock(return_value=mock_result)

        response = await list_scripts(project_id=None, case_id=None, db=db)

        assert response["code"] == 0
        assert response["data"][0]["name"] == "a.py"
        assert "ai_suggested" not in response["data"][0]
        assert "actual_included" not in response["data"][0]

    @pytest.mark.asyncio
    async def test_list_with_param_adds_fields(self):
        """include_regression=true → item 追加回归四字段."""
        from app.api.v1.scripts import list_scripts

        mock_script = MagicMock()
        mock_script.to_dict = MagicMock(return_value={"id": "s1", "name": "a.py"})
        mock_reg = MagicMock(ai_suggested=True, ai_reason="P0核心用例",
                             actual_included=True, include_source="ai")
        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([mock_script, mock_reg])
        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[(mock_script, mock_reg)])
        mock_result.scalars = MagicMock()
        db = MagicMock()
        db.execute = AsyncMock(return_value=mock_result)

        response = await list_scripts(
            project_id=None, case_id=None, include_regression=True, db=db
        )

        assert response["code"] == 0
        item = response["data"][0]
        assert item["ai_suggested"] is True
        assert item["ai_reason"] == "P0核心用例"
        assert item["actual_included"] is True
        assert item["include_source"] == "ai"
        # 联查语句包含 outerjoin
        stmt = db.execute.await_args.args[0]
        assert "JOIN" in str(stmt.compile()).upper()

    @pytest.mark.asyncio
    async def test_list_with_param_no_regression_row(self):
        """include_regression=true 且脚本无回归记录 → 字段取缺省值."""
        from app.api.v1.scripts import list_scripts

        mock_script = MagicMock()
        mock_script.to_dict = MagicMock(return_value={"id": "s2", "name": "b.py"})
        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[(mock_script, None)])
        db = MagicMock()
        db.execute = AsyncMock(return_value=mock_result)

        response = await list_scripts(
            project_id=None, case_id=None, include_regression=True, db=db
        )

        item = response["data"][0]
        assert item["ai_suggested"] is False
        assert item["ai_reason"] is None
        assert item["actual_included"] is False
        assert item["include_source"] is None
