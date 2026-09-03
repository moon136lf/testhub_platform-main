"""
MoonTest Backend Application
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import json
import time
import logging
import uuid

from app.core.config import settings
from app.core.database import engine, init_db
from app.core.redis import redis_client
from app.api import api_router

# Configure logging
import os

from app.core.logging_setup import setup_logging, set_request_id

setup_logging(log_dir=os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs"),
              level_console=os.getenv("LOG_LEVEL") or settings.LOG_LEVEL)
logging.getLogger("sqlalchemy.engine").setLevel(settings.SQLALCHEMY_LEVEL.upper())
logging.getLogger("uvicorn.access").disabled = True  # 用自己的访问日志
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting MoonTest application...")
    await init_db()
    logger.info("Database initialized")
    await redis_client.connect()  # SSE 流依赖（不连则 redis_client.redis 为 None）
    logger.info("Redis initialized")

    yield

    # Shutdown
    logger.info("Shutting down MoonTest application...")
    await redis_client.close()
    await engine.dispose()
    logger.info("Database connections closed")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="MoonTest AI-Driven Testing Platform",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Configure specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # requestId: 透传上游 X-Request-Id（跨系统链路串联），无则生成
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    set_request_id(rid)
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    client = request.client.host if request.client else "-"

    # SSE 流端点不记访问行（响应"完成"在流关闭时，通常数十分钟后，访问行无意义）；
    # 建立/关闭日志由 sse.py 输出（requestId 由 root filter 自动注入）
    media_type = getattr(response, "media_type", "") or ""
    if "event-stream" in media_type or request.url.path.startswith("/api/sse"):
        response.headers["X-Request-Id"] = rid
        return response

    # body 摘要（≤2KB JSON，敏感字段打码）
    body_digest = "-"
    try:
        if (request.headers.get("content-type") or "").startswith("application/json"):
            body_bytes = await request.body()
            if 0 < len(body_bytes) <= 2048:
                parsed = json.loads(body_bytes)
                body_digest = json.dumps(_mask(parsed), ensure_ascii=False)[:512]
            elif len(body_bytes) > 2048:
                body_digest = "<2KB截断>"
    except Exception:
        pass

    line = (f"HTTP {request.method} {request.url.path} -> {response.status_code}, "
            f"requestId={rid}, costMs={ms:.0f}, client={client}, body={body_digest}")
    if response.status_code >= 500:
        logger.error(line)
    elif ms >= 3000:
        logger.warning(line)
    else:
        logger.info(line)
    response.headers["X-Request-Id"] = rid
    return response


# ---- 访问行 body 打码 ----
_SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "passwd", "authorization"}


def _mask(value, depth: int = 0):
    """body 摘要敏感字段打码: key 模糊匹配 → ***"""
    if depth > 6:
        return "..."
    if isinstance(value, dict):
        return {k: ("***" if any(s in str(k).lower() for s in _SENSITIVE_KEYS)
                    else _mask(v, depth + 1))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v, depth + 1) for v in value]
    return value


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"【系统】未处理异常 | path={request.url.path} 原因={exc}")
    return JSONResponse(
        status_code=500,
        content={
            "code": 50001,
            "message": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An error occurred"
        }
    )


# Include API routes
app.include_router(api_router, prefix="/api/v1")

# Include SSE routes (separate from /api/v1)
from app.api import sse_router
app.include_router(sse_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "database": "connected"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
