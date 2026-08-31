"""Regression (#8) schemas."""
from pydantic import BaseModel, Field
from typing import Any, List, Literal


class MembersRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    script_ids: List[str] = Field(..., min_length=1)
    action: Literal["add", "remove"]


class IdentifyRequest(BaseModel):
    project_id: str = Field(..., min_length=1)


class RegressionRunConfig(BaseModel):
    headless: bool = True
    timeout: int = Field(60, ge=5, le=600)
    max_failures: int = Field(8, ge=1, le=100)
    fail_fast: bool = Field(False, description="失败策略: false=继续(默认)/true=停止")


class RunRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    config: RegressionRunConfig = RegressionRunConfig()


class RegResponse(BaseModel):
    code: int = 0
    data: Any = None
