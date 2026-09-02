"""Request logging middleware + global exception handler tests."""
import logging

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import app


class TestRequestLogging:
    def test_middleware_logs_method_path_status(self, caplog):
        with caplog.at_level(logging.INFO, logger="app.main"):
            client = TestClient(app)
            resp = client.get("/health")
        assert resp.status_code in (200, 404)  # 只要有响应就产生日志行
        assert any(" -> " in r.message for r in caplog.records)


class TestGlobalExceptionHandler:
    def test_unhandled_exception_returns_500(self, caplog):
        r = APIRouter()

        @r.get("/__boom__")
        async def boom():
            raise RuntimeError("boom-test")

        app.include_router(r, prefix="/api/v1")
        try:
            with caplog.at_level(logging.ERROR, logger="app.main"):
                resp = TestClient(app, raise_server_exceptions=False).get("/api/v1/__boom__")
            assert resp.status_code == 500
            assert "boom-test" in caplog.text
        finally:
            # 清理临时路由, 避免污染其他测试
            app.router.routes = [rt for rt in app.router.routes
                                 if getattr(rt, "path", "") != "/api/v1/__boom__"]
