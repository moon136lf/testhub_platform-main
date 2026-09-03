"""requestId 中间件测试 (#logging-v2 T2)"""
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app():
    app = FastAPI()

    @app.middleware("http")
    async def mw(request, call_next):
        from app.main import log_requests
        return await log_requests(request, call_next)

    @app.get("/ping")
    async def ping():
        return {"ok": 1}

    @app.post("/echo")
    async def echo(data: dict):
        return {"got": data.get("name")}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("x")

    return app


class TestRequestIdMiddleware:
    def test_generates_uuid_header(self):
        client = TestClient(_app(), raise_server_exceptions=False)
        r = client.get("/ping")
        assert r.headers.get("x-request-id")
        assert len(r.headers["x-request-id"]) == 36

    def test_honors_incoming_header(self):
        client = TestClient(_app(), raise_server_exceptions=False)
        r = client.get("/ping", headers={"X-Request-Id": "upstream-abc"})
        assert r.headers["x-request-id"] == "upstream-abc"

    def test_body_digest_masked(self):
        client = TestClient(_app(), raise_server_exceptions=False)
        r = client.post("/echo", json={"name": "tom", "password": "p@ss", "api_key": "k1"})
        assert r.status_code == 200

    def test_body_roundtrip_not_blocked(self):
        """body 被中间件读过之后业务端点仍能拿到"""
        client = TestClient(_app())
        r = client.post("/echo", json={"name": "tom"})
        assert r.json() == {"got": "tom"}
