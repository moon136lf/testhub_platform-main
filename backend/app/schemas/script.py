"""Script conversion schemas."""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any


# ===== Enum canonical values =====
LOCATOR_SOURCES = ("element_library", "ai_generated", "mixed", "none_draft")
SCRIPT_STATUSES = ("draft", "generated", "confirmed")
ERROR_TYPES = ("locate_failed", "timeout", "assertion_failed", "script_error")
DIAGNOSIS_CATEGORIES = ("script_problem", "page_bug", "data_env", "ambiguous")


def _pattern(values: tuple) -> str:
    return "^(" + "|".join(values) + ")$"


class ConvertRequest(BaseModel):
    project_id: str = Field(..., description="Project ID")
    case_ids: List[str] = Field(..., min_length=1, description="已定稿用例 ID 列表")
    ai_optimize: bool = Field(False, description="未命中时是否调 AI 生成定位器")


class ConvertResponse(BaseModel):
    code: int = 0
    data: Dict[str, Any]


class ScriptResponse(BaseModel):
    id: str
    project_id: str
    case_id: str
    name: str
    description: Optional[str] = None
    content: str
    version: int
    status: str
    category: str
    locator_source: str
    step_mapping: Optional[List[Dict]] = None
    ai_diagnosis: Optional[Dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConfirmResponse(BaseModel):
    code: int = 0
    message: str
    data: Dict[str, Any]


class DiagnoseRequest(BaseModel):
    error_type: str = Field(..., pattern=_pattern(ERROR_TYPES), description="错误类型")
    error_msg: str = Field(..., min_length=1, max_length=2000)
    script_fragment: str = Field(..., min_length=1, max_length=10000)
    dom_snapshot: Optional[str] = Field(None, max_length=50000)
    screenshot_url: Optional[str] = Field(None, max_length=500)
    failed_step: Optional[int] = Field(None, ge=1)


class DiagnosisCard(BaseModel):
    category: str = Field(..., pattern=_pattern(DIAGNOSIS_CATEGORIES))
    can_fix: bool
    reason: str
    failed_step: Optional[int] = None
    error_type: Optional[str] = None
    error_msg: Optional[str] = None
    screenshot_url: Optional[str] = None
    revised_step: Optional[str] = None
    suggestion: str


class DiagnoseResponse(BaseModel):
    code: int = 0
    data: Dict[str, Any]


SCRIPT_LAST_STATUSES = ("never_run", "passed", "failed", "affected")
SCRIPT_CATEGORIES = ("uncategorized", "ui_smoke", "full_regression", "core_flow", "interface_auto")


class RunConfig(BaseModel):
    headless: bool = Field(True, description="有头/无头模式")
    timeout: int = Field(60, ge=5, le=600, description="单测试超时秒")
    max_failures: int = Field(8, ge=1, le=100, description="最大失败数")


class RunRequest(BaseModel):
    script_id: str = Field(..., description="脚本 ID (UUID)")
    config: RunConfig = Field(default_factory=RunConfig)

    @field_validator("script_id")
    @classmethod
    def _valid_uuid(cls, v):
        import uuid
        uuid.UUID(v)
        return v


class BatchRunRequest(BaseModel):
    script_ids: List[str] = Field(..., min_length=1, description="脚本 ID 列表")
    config: RunConfig = Field(default_factory=RunConfig)


class QuickRunRequest(BaseModel):
    script_content: str = Field(..., min_length=1, description="临时粘贴的 Playwright Python 脚本")
    target_url: str = Field(..., description="被测 URL")
    headless: bool = Field(True, description="运行模式")
