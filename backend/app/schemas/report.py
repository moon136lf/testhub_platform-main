"""Report schemas."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class ExecutionRecordResponse(BaseModel):
    id: str
    exec_id: str
    project_id: str
    exec_type: str
    status: str
    total_cases: int = 0
    passed_count: int = 0
    fail_count: int = 0
    pass_rate: float = 0.0
    duration_ms: int = 0
    tokens_used: int = 0
    env_info: Optional[Dict[str, Any]] = None
    report_url: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class ExecutionRecordListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ExecutionRecordResponse]


class ExecutionDetailResponse(BaseModel):
    id: str
    execution_record_id: str
    script_id: Optional[str] = None
    case_id: Optional[str] = None
    step: Optional[int] = None
    action: Optional[str] = None
    status: str
    error_type: Optional[str] = None
    error_msg: Optional[str] = None
    stack_trace: Optional[str] = None
    screenshot_url: Optional[str] = None
    dom_snapshot: Optional[str] = None
    heal_status: Optional[str] = None
    heal_log: Optional[Any] = None
    duration_ms: int = 0
    created_at: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class ReportDetailResponse(BaseModel):
    """报告详情：ExecutionRecord + 聚合统计 + 失败明细"""
    record: ExecutionRecordResponse
    fail_step_count: int = 0
    total_duration_ms: int = 0
    token_remaining: Optional[int] = None
    details: List[ExecutionDetailResponse] = []


class TrendItem(BaseModel):
    date: str
    pass_rate: float = 0.0
    exec_count: int = 0


class TrendResponse(BaseModel):
    project_id: str
    days: int
    items: List[TrendItem]


class GenerateReportResponse(BaseModel):
    html_url: Optional[str] = None
    pdf_url: Optional[str] = None
    regenerated: bool = False
