"""Whitescan schemas."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ScanTriggerRequest(BaseModel):
    project_id: str
    repo_url: str = Field(..., min_length=1, max_length=500)
    branch: str = Field("main", max_length=100)


class ScanResponse(BaseModel):
    id: str
    project_id: str
    repo_url: str
    branch: str
    status: str
    total_issues: int = 0
    high_count: int = 0
    mid_count: int = 0
    low_count: int = 0
    file_count: int = 0
    duration_ms: int = 0
    error_msg: Optional[str] = None
    created_at: Optional[str] = None


class ScanListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ScanResponse] = []


class IssueResponse(BaseModel):
    id: str
    scan_id: str
    severity: str
    file_path: str
    line_no: Optional[int] = None
    title: str
    description: Optional[str] = None
    ai_suggestion: Optional[Dict[str, Any]] = None
    example_code: Optional[str] = None
    status: str
    fingerprint: Optional[str] = None
    case_outdated: bool = False
    handled_by: Optional[str] = None
    handled_at: Optional[str] = None


class IssueUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(open|fixed|false_positive)$")
    handled_by: Optional[str] = None


class GenerateCaseResult(BaseModel):
    generated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    errors: List[Dict[str, Any]] = []
