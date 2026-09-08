"""
API router configuration
"""

from fastapi import APIRouter

from app.api.v1 import projects, health, elements, sse, ai_case_generation, test_cases, scripts, system, reports, dashboard, diagnostics, regression, reviews, whitescan, test_sets

api_router = APIRouter()

# Include sub-routers
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(elements.router, prefix="/elements", tags=["elements"])
api_router.include_router(elements.asset_router, tags=["element-assets"])  # 阶段1: 无前缀（路径自带 elements-asset 等）
api_router.include_router(ai_case_generation.router, prefix="/ai-case-generation", tags=["ai-case-generation"])
api_router.include_router(test_cases.router, prefix="/test-cases", tags=["test-cases"])
api_router.include_router(scripts.router, prefix="/scripts", tags=["scripts"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(regression.router, prefix="/regression", tags=["regression"])
api_router.include_router(diagnostics.router, prefix="/diagnostics", tags=["diagnostics"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(whitescan.router, prefix="/whitescan", tags=["whitescan"])
api_router.include_router(test_sets.router, tags=["test-sets"])  # 阶段2: 无前缀（路径自带 test-sets）

# SSE router (separate prefix)
sse_router = APIRouter()
sse_router.include_router(sse.router, prefix="/sse", tags=["sse"])
