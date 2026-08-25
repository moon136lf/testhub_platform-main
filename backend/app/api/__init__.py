"""
API router configuration
"""

from fastapi import APIRouter

from app.api.v1 import projects, health, elements, sse, ai_case_generation, test_cases, scripts, system

api_router = APIRouter()

# Include sub-routers
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(elements.router, prefix="/elements", tags=["elements"])
api_router.include_router(ai_case_generation.router, prefix="/ai-case-generation", tags=["ai-case-generation"])
api_router.include_router(test_cases.router, prefix="/test-cases", tags=["test-cases"])
api_router.include_router(scripts.router, prefix="/scripts", tags=["scripts"])
api_router.include_router(system.router, prefix="/system", tags=["system"])

# SSE router (separate prefix)
sse_router = APIRouter()
sse_router.include_router(sse.router, prefix="/sse", tags=["sse"])
