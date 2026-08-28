"""Diagnostics (#5c) schemas."""
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional


class ErrorDataOverride(BaseModel):
    """TRANS-05 可选覆盖 (spec §1.4 入参偏差)."""
    error_type: Optional[str] = None
    error_msg: Optional[str] = None
    screenshot_url: Optional[str] = None
    dom_snapshot: Optional[str] = None
    script_fragment: Optional[str] = None


class AnalyzeRequest(BaseModel):
    execution_id: str = Field(..., min_length=1, max_length=50,
                              description="ExecutionRecord.exec_id")
    step: Optional[int] = Field(None, ge=1, description="失败步骤号, 缺省取第一个 fail")
    error_data: Optional[ErrorDataOverride] = None


class ApplyRequest(BaseModel):
    script_id: str = Field(..., description="脚本 ID (诊断卡归属)")
    project_id: str = Field(..., description="项目 ID (元素库查询隔离)")
    element_name: str = Field(..., min_length=1, max_length=100)
    new_locator: str = Field(..., min_length=1, max_length=500)
    confidence: Optional[float] = Field(None, ge=0, le=1)


class DiagResponse(BaseModel):
    code: int = 0
    data: Dict[str, Any]
