"""
MoonTest Backend Application
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time
import logging

from app.core.config import settings
from app.core.database import engine, init_db
from app.core.redis import redis_client
from app.api import api_router

# Configure logging
import os

from app.core.logging_setup import setup_logging

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
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    line = f"{request.method} {request.url.path} -> {response.status_code} ({ms:.0f}ms)"
    if response.status_code >= 500:
        logger.error(line)
    elif ms >= 3000:
        logger.warning(line)
    else:
        logger.info(line)
    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception | {request.method} {request.url.path}: {exc}")
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
