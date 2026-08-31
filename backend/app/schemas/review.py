"""Review center schemas (#7)."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from app.schemas.test_case import REVIEW_STATUSES


class ReviewStatsResponse(BaseModel):
    review_status: Dict[str, int] = {}
    feasibility: Dict[str, int] = {}
    automation_rate: float = 0.0
    total_cases: int = 0


class BatchRefineRequest(BaseModel):
    project_id: str
    case_ids: List[str] = Field(..., min_length=1)


class BatchRefineResultItem(BaseModel):
    case_id: str
    score: Optional[int] = None
    feasibility_level: Optional[str] = None
    suggestion_count: Optional[int] = None
    error: Optional[str] = None


class SuggestionWithCase(BaseModel):
    case_id: str
    case_name: str
    id: Optional[str] = None
    dimension: Optional[str] = None
    severity: Optional[str] = None
    target_step: Optional[int] = None
    issue: Optional[str] = None
    suggestion: Optional[str] = None
    status: Optional[str] = None


class ProjectRefinementReportResponse(BaseModel):
    case_count: int = 0
    refined_at: Optional[str] = None
    suggestions: List[SuggestionWithCase] = []


class BatchReviewRequest(BaseModel):
    project_id: str
    case_ids: List[str] = Field(..., min_length=1)
    review_status: str
    review_comment: Optional[str] = Field(None, max_length=500)

    @field_validator("review_status")
    @classmethod
    def status_valid(cls, v):
        if v not in REVIEW_STATUSES:
            raise ValueError(f"review_status must be one of {REVIEW_STATUSES}")
        return v


class BatchReviewResponse(BaseModel):
    success_count: int = 0
    failure_count: int = 0
