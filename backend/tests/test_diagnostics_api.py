"""Diagnostics API tests (mock DiagnosticsService)."""
from unittest.mock import patch

from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


class TestAnalyzeEndpoint:
    def test_analyze_success_contract(self):
        """§9.2.5 契约: 响应含 diagnosis/suggestion/new_locator/confidence/apply_url."""
        from app.api.v1 import diagnostics as diag_mod

        async def fake_analyze(self, exec_id, step=None, override=None, detail_id=None):
            return {"diagnosis": "d", "suggestion": "s", "new_locator": "#x",
                    "confidence": 0.9, "apply_url": "/api/v1/diagnostics/apply",
                    "card": {"mode": "multimodal"}}

        with patch.object(diag_mod.DiagnosticsService, "analyze", fake_analyze):
            client = _client()
            resp = client.post("/api/v1/diagnostics/analyze", json={
                "execution_id": "exec-abc12345", "step": 3})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        for k in ("diagnosis", "suggestion", "new_locator", "confidence", "apply_url"):
            assert k in body["data"]

    def test_analyze_detail_missing_404(self):
        from app.api.v1 import diagnostics as diag_mod

        async def fake_analyze(self, exec_id, step=None, override=None, detail_id=None):
            raise ValueError("未找到失败记录: exec_id=x")

        with patch.object(diag_mod.DiagnosticsService, "analyze", fake_analyze):
            client = _client()
            resp = client.post("/api/v1/diagnostics/analyze", json={
                "execution_id": "exec-missing"})
        assert resp.status_code == 404

    def test_analyze_gateway_unavailable_503(self):
        from app.api.v1 import diagnostics as diag_mod

        async def fake_analyze(self, exec_id, step=None, override=None, detail_id=None):
            raise ConnectionError("Provider 'moonshot' not available.")

        with patch.object(diag_mod.DiagnosticsService, "analyze", fake_analyze):
            client = _client()
            resp = client.post("/api/v1/diagnostics/analyze", json={
                "execution_id": "exec-x"})
        assert resp.status_code == 503

    def test_analyze_bad_body_422(self):
        client = _client()
        resp = client.post("/api/v1/diagnostics/analyze", json={})
        assert resp.status_code == 422  # execution_id 必填

    def test_analyze_detail_id_passthrough(self):
        """T8 fixup C2: detail_id 透传给 service (batch 多脚本同 step 直取)."""
        from app.api.v1 import diagnostics as diag_mod

        captured = {}

        async def fake_analyze(self, exec_id, step=None, override=None, detail_id=None):
            captured["detail_id"] = detail_id
            captured["override"] = override
            return {"diagnosis": "d", "suggestion": "s", "new_locator": None,
                    "confidence": None, "apply_url": "/api/v1/diagnostics/apply",
                    "card": {}}

        with patch.object(diag_mod.DiagnosticsService, "analyze", fake_analyze):
            client = _client()
            resp = client.post("/api/v1/diagnostics/analyze", json={
                "execution_id": "exec-x", "step": 2,
                "detail_id": "0f0e0d0c-0b0a-4948-8276-000000000001",
                "error_data": {"error_type": "locate_failed", "dom_snapshot": "<html>x</html>"}})
        assert resp.status_code == 200
        assert captured["detail_id"] == "0f0e0d0c-0b0a-4948-8276-000000000001"
        # I1: exclude_none — 未填字段不产生显式 None 键
        assert captured["override"] == {"error_type": "locate_failed",
                                        "dom_snapshot": "<html>x</html>"}


class TestApplyEndpoint:
    def test_apply_success(self):
        from app.api.v1 import diagnostics as diag_mod

        async def fake_apply(self, **kw):
            return {"element_id": "login-btn", "updated": True,
                    "cleaned_locator": "#new-login-btn"}

        with patch.object(diag_mod.DiagnosticsService, "apply", fake_apply):
            client = _client()
            resp = client.post("/api/v1/diagnostics/apply", json={
                "script_id": "0f0e0d0c-0b0a-4948-8276-000000000000",
                "project_id": "1a2b3c4d-5e6f-4948-8276-000000000000",
                "element_name": "登录按钮",
                "new_locator": "#new-login-btn", "confidence": 0.92})
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] is True

    def test_apply_invalid_locator_400(self):
        from app.api.v1 import diagnostics as diag_mod

        async def fake_apply(self, **kw):
            raise ValueError("定位器无效（含 page.get_by_* 表达式或格式非法）: page.get_by_role(...)")

        with patch.object(diag_mod.DiagnosticsService, "apply", fake_apply):
            client = _client()
            resp = client.post("/api/v1/diagnostics/apply", json={
                "script_id": "0f0e0d0c-0b0a-4948-8276-000000000000",
                "project_id": "1a2b3c4d-5e6f-4948-8276-000000000000",
                "element_name": "登录按钮",
                "new_locator": "page.get_by_role(\"button\")", "confidence": 0.9})
        assert resp.status_code == 400
