"""System settings API endpoints (prefix /system)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.system_setting_service import SystemSettingService
from app.services.test_env_service import TestEnvService
from app.services.token_service import TokenService
from app.services.operation_log_service import OperationLogService, log_operation
from app.schemas.system import (
    SettingUpdate, SettingResponse, TestConnectionRequest, TestConnectionResponse,
    RuntimeConfigResponse, TestEnvCreate, TestEnvUpdate, TestEnvResponse,
    TokenQuotaUpdate, OperationLogResponse,
)

router = APIRouter()


# ---- service factories ----
def get_setting_service(db: AsyncSession = Depends(get_db)) -> SystemSettingService:
    return SystemSettingService(db)

def get_env_service(db: AsyncSession = Depends(get_db)) -> TestEnvService:
    return TestEnvService(db)

def get_token_service(db: AsyncSession = Depends(get_db)) -> TokenService:
    return TokenService(db)

def get_oplog_service(db: AsyncSession = Depends(get_db)) -> OperationLogService:
    return OperationLogService(db)


# ---- settings ----
@router.get("/settings")
async def list_settings(
    category: str = Query(..., pattern="^(ai|runtime)$"),
    svc: SystemSettingService = Depends(get_setting_service),
):
    rows = await svc.list(category)
    return {"code": 0, "data": [SettingResponse(**r) for r in rows]}


@router.get("/settings/{key}")
async def get_setting(
    key: str,
    category: str = Query(..., pattern="^(ai|runtime)$"),
    reveal: bool = Query(False),
    svc: SystemSettingService = Depends(get_setting_service),
):
    val = await svc.get(key, category=category)
    return {"code": 0, "data": {"key": key, "value": val}}


@router.put("/settings/{key}")
async def update_setting(
    key: str,
    body: SettingUpdate,
    category: str = Query(..., pattern="^(ai|runtime)$"),
    svc: SystemSettingService = Depends(get_setting_service),
    oplog: OperationLogService = Depends(get_oplog_service),
):
    await svc.set(category, key, body.value, value_type=body.value_type,
                  is_secret=body.is_secret, description=body.description,
                  updated_by=body.updated_by)
    await log_operation(oplog.db, "system", "update_setting", "setting", key,
                        detail={"category": category, "value_type": body.value_type},
                        operator=body.updated_by or "system")
    return {"code": 0, "message": "Setting updated"}


@router.post("/settings/test-connection", response_model=TestConnectionResponse)
async def test_connection(body: TestConnectionRequest):
    """Ping a provider with current config to verify the key."""
    from app.services.ai_gateway import ai_gateway
    provider = body.provider
    if provider not in ai_gateway._providers:
        return TestConnectionResponse(success=False, message=f"Provider '{provider}' not configured", model=None)
    try:
        await ai_gateway.chat(
            [{"role": "user", "content": "ping"}], provider=provider,
        )
        return TestConnectionResponse(success=True, message="Connection OK", model=provider)
    except Exception as e:
        return TestConnectionResponse(success=False, message=str(e), model=provider)


# ---- runtime config ----
@router.get("/runtime-config", response_model=RuntimeConfigResponse)
async def get_runtime_config(svc: SystemSettingService = Depends(get_setting_service)):
    """Aggregate runtime config from system_setting (falls back to settings defaults)."""
    from app.core.config import settings

    async def _g(k, default, cast=None):
        v = await svc.get(k, category="runtime", default=default)
        try:
            return cast(v) if cast else v
        except (TypeError, ValueError):
            return default

    return RuntimeConfigResponse(
        heal_strategy=await _g("heal.strategy", "SMART"),
        heal_confidence_threshold=await _g("heal.confidence_threshold", settings.HEAL_CONFIDENCE_THRESHOLD, int),
        heal_cache_ttl_success=await _g("heal.cache_ttl_success", settings.HEAL_CACHE_TTL_SUCCESS, int),
        heal_cache_ttl_fail=await _g("heal.cache_ttl_fail", settings.HEAL_CACHE_TTL_FAIL, int),
        execution_timeout=await _g("execution.timeout", settings.EXECUTION_TIMEOUT, int),
        max_retry_count=await _g("execution.max_retry", settings.MAX_RETRY_COUNT, int),
        sse_timeout=await _g("sse.timeout", settings.SSE_TIMEOUT, int),
    )


# ---- test env ----
@router.get("/envs")
async def list_envs(svc: TestEnvService = Depends(get_env_service)):
    rows = await svc.list()
    return {"code": 0, "data": [TestEnvResponse(**r) for r in rows]}


@router.post("/envs", status_code=201)
async def create_env(body: TestEnvCreate, svc: TestEnvService = Depends(get_env_service),
                     oplog: OperationLogService = Depends(get_oplog_service)):
    env = await svc.create(body.model_dump())
    await log_operation(oplog.db, "system", "create_env", "test_env", env["id"],
                        detail={"name": env["name"]}, operator=body.created_by or "system")
    return {"code": 0, "data": TestEnvResponse(**env)}


@router.put("/envs/{env_id}")
async def update_env(env_id: str, body: TestEnvUpdate,
                     svc: TestEnvService = Depends(get_env_service)):
    env = await svc.update(env_id, body.model_dump(exclude_unset=True))
    if not env:
        raise HTTPException(status_code=404, detail="Env not found")
    return {"code": 0, "data": TestEnvResponse(**env)}


@router.delete("/envs/{env_id}")
async def delete_env(env_id: str, svc: TestEnvService = Depends(get_env_service)):
    ok = await svc.delete(env_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Env not found")
    return {"code": 0, "message": "Env deleted"}


# ---- operation logs ----
@router.get("/operation-logs")
async def list_oplogs(
    module: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    svc: OperationLogService = Depends(get_oplog_service),
):
    items, total = await svc.list(module=module, page=page, page_size=page_size)
    return {"code": 0, "data": {"items": [OperationLogResponse(**r) for r in items],
                                "total": total, "page": page, "page_size": page_size}}


# ---- tokens ----
@router.get("/tokens/status")
async def token_status(project_id: str = Query(...),
                       svc: TokenService = Depends(get_token_service)):
    st = await svc.get_status(project_id)
    return {"code": 0, "data": st.model_dump()}


@router.get("/tokens/quota")
async def token_quota_get(project_id: str = Query(...),
                          svc: TokenService = Depends(get_token_service)):
    return {"code": 0, "data": await svc.get_quota(project_id)}


@router.put("/tokens/quota")
async def token_quota_update(project_id: str = Query(...), body: TokenQuotaUpdate = None,
                             svc: TokenService = Depends(get_token_service),
                             oplog: OperationLogService = Depends(get_oplog_service)):
    result = await svc.update_quota(project_id,
                                    total_quota=body.total_quota if body else None,
                                    alert_threshold=body.alert_threshold if body else None)
    await log_operation(oplog.db, "system", "update_token_quota", "token_quota", project_id,
                        detail=result, operator="system")
    return {"code": 0, "data": result}


@router.get("/tokens/usage")
async def token_usage(project_id: str = Query(...),
                      days: int = Query(7, ge=1, le=90),
                      svc: TokenService = Depends(get_token_service)):
    usage = await svc.get_usage(project_id, days)
    return {"code": 0, "data": usage.model_dump()}
