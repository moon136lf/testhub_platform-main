"""System settings schemas."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ---- system_setting ----
class SettingUpdate(BaseModel):
    value: str
    value_type: str = Field("string", pattern="^(string|int|float|bool|json)$")
    is_secret: bool = False
    description: Optional[str] = Field(None, max_length=500)
    updated_by: Optional[str] = Field(None, max_length=50)


class SettingResponse(BaseModel):
    id: str
    category: str
    key: str
    value: Optional[Any] = None
    value_type: str = "string"
    is_secret: bool = False
    description: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class TestConnectionRequest(BaseModel):
    provider: str = Field(..., description="provider name: glm-4/qwen/deepseek/claude")


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    model: Optional[str] = None


# ---- runtime config ----
class RuntimeConfigResponse(BaseModel):
    """Aggregated runtime config for display."""
    heal_strategy: str = "SMART"
    heal_confidence_threshold: int = 3
    heal_cache_ttl_success: int = 30
    heal_cache_ttl_fail: int = 1
    execution_timeout: int = 600
    max_retry_count: int = 3
    sse_timeout: int = 1800
    model_config = ConfigDict(from_attributes=True)


# ---- test_env ----
class TestEnvCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    url: str = Field(..., min_length=1, max_length=500)
    env_type: str = Field("dev", pattern="^(dev|staging|prod)$")
    status: str = Field("active", pattern="^(active|inactive)$")
    credentials: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = Field(None, max_length=50)


class TestEnvUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    url: Optional[str] = Field(..., min_length=1, max_length=500)
    env_type: Optional[str] = Field(None, pattern="^(dev|staging|prod)$")
    status: Optional[str] = Field(None, pattern="^(active|inactive)$")
    credentials: Optional[Dict[str, Any]] = None


class TestEnvResponse(BaseModel):
    id: str
    name: str
    url: str
    env_type: str
    status: str
    credentials: Dict[str, Any] = {}
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# ---- operation_log ----
class OperationLogResponse(BaseModel):
    id: str
    module: str
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    operator: Optional[str] = None
    ip: Optional[str] = None
    created_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# ---- token ----
class TokenQuotaUpdate(BaseModel):
    total_quota: Optional[int] = Field(None, ge=0)
    alert_threshold: Optional[int] = Field(None, ge=0, le=100)


class TokenQuotaResponse(BaseModel):
    project_id: str
    total_quota: int
    alert_threshold: int
    updated_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class TokenStatusResponse(BaseModel):
    """Aligned with requirement §9.2.6."""
    total_quota: int
    used: int
    remaining: int
    percentage: float
    is_warning: bool
    warning_threshold: int
    recent_daily_avg: float
    estimated_days_remaining: Optional[int] = None


class TokenUsageItem(BaseModel):
    label: str  # stage or model
    tokens: int
    model_config = ConfigDict(from_attributes=True)


class TokenUsageResponse(BaseModel):
    by_stage: List[TokenUsageItem]
    by_model: List[TokenUsageItem]
    daily: List[Dict[str, Any]]  # [{date, tokens}]
    model_config = ConfigDict(from_attributes=True)
