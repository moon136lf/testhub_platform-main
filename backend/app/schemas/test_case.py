"""
Test case schemas for request/response validation
"""

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import Optional, List, Dict, Any

# ===== Enum canonical values (source of truth) =====
CASE_TYPES = ("functional", "interface_case")
AUTOMATION_STATUSES = ("pending", "automated", "partial_automated")
# REVIEW_STATUSES / FEASIBILITY_LEVELS 用于后续 W5 评审/精修字段
REVIEW_STATUSES = ("pending", "passed", "needs_revision")
FEASIBILITY_LEVELS = ("full", "partial", "manual")
HALLUCINATION_STATUSES = ("normal", "suspected", "confirmed")


def _pattern(values: tuple) -> str:
    return "^(" + "|".join(values) + ")$"


class StepSchema(BaseModel):
    """Schema for test step validation"""
    step: int = Field(..., ge=1, description="Step sequence number, must be >= 1")
    action: str = Field(..., min_length=1, max_length=200, description="Test action description")
    target: Optional[str] = Field(None, max_length=200, description="Target element or object")
    data: Optional[str] = Field(None, max_length=200, description="Test data or input")
    expected: str = Field(..., min_length=1, max_length=200, description="Expected result for this step")

    model_config = ConfigDict(from_attributes=True)


class CaseFilterParams(BaseModel):
    """Schema for test case filter parameters"""
    project_id: str = Field(..., description="Project ID (required)")
    point_id: Optional[str] = Field(None, description="Filter by test point ID")
    priority: Optional[str] = Field(None, pattern="^(P0|P1|P2|P3)$", description="Priority level")
    case_type: Optional[str] = Field(None, pattern=_pattern(CASE_TYPES))
    automation_status: Optional[str] = Field(None, pattern=_pattern(AUTOMATION_STATUSES))
    is_finalized: Optional[bool] = Field(None, description="Finalized status")
    hallucination_status: Optional[str] = Field(None, pattern=_pattern(HALLUCINATION_STATUSES))
    keyword: Optional[str] = Field(None, max_length=100, description="Search keyword for name/steps")
    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")

    model_config = ConfigDict(from_attributes=True)


class CaseCreateRequest(BaseModel):
    """Schema for test case creation request"""
    project_id: str = Field(..., description="Project ID")
    point_id: Optional[str] = Field(None, description="Associated test point ID")
    name: str = Field(..., min_length=1, max_length=100, description="Test case name")
    priority: str = Field("P1", pattern="^(P0|P1|P2|P3)$", description="Priority level")
    case_type: str = Field("functional", pattern=_pattern(CASE_TYPES))
    automation_status: str = Field("pending", pattern=_pattern(AUTOMATION_STATUSES))
    precondition: Optional[str] = Field(None, description="Test preconditions")
    steps: List[StepSchema] = Field(..., min_length=1, description="Test steps (at least 1 required)")
    expected_result: str = Field(..., min_length=1, max_length=200, description="Overall expected result")
    created_by: Optional[str] = Field(None, max_length=50, description="Creator username")

    @field_validator('steps')
    @classmethod
    def validate_steps_sequence(cls, v: List[StepSchema]) -> List[StepSchema]:
        """Validate that step sequence numbers are continuous starting from 1"""
        if not v:
            raise ValueError("At least one step is required")

        step_numbers = sorted([step.step for step in v])
        expected_numbers = list(range(1, len(v) + 1))

        if step_numbers != expected_numbers:
            raise ValueError(
                f"Step sequence numbers must be continuous starting from 1. "
                f"Expected {expected_numbers}, got {step_numbers}"
            )

        return v

    model_config = ConfigDict(from_attributes=True)


class CaseUpdateRequest(BaseModel):
    """Schema for test case update request (all fields optional)"""
    point_id: Optional[str] = Field(None, description="Associated test point ID")
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Test case name")
    priority: Optional[str] = Field(None, pattern="^(P0|P1|P2|P3)$", description="Priority level")
    case_type: Optional[str] = Field(None, pattern=_pattern(CASE_TYPES))
    automation_status: Optional[str] = Field(None, pattern=_pattern(AUTOMATION_STATUSES))
    precondition: Optional[str] = Field(None, description="Test preconditions")
    steps: Optional[List[StepSchema]] = Field(None, min_length=1, description="Test steps")
    expected_result: Optional[str] = Field(None, min_length=1, max_length=200, description="Overall expected result")
    is_finalized: Optional[bool] = Field(None, description="Finalized status")
    hallucination_status: Optional[str] = Field(None, pattern=_pattern(HALLUCINATION_STATUSES))

    @field_validator('steps')
    @classmethod
    def validate_steps_sequence(cls, v: Optional[List[StepSchema]]) -> Optional[List[StepSchema]]:
        """Validate that step sequence numbers are continuous starting from 1 if steps are provided"""
        if v is None:
            return v

        if not v:
            raise ValueError("If steps are provided, at least one step is required")

        step_numbers = sorted([step.step for step in v])
        expected_numbers = list(range(1, len(v) + 1))

        if step_numbers != expected_numbers:
            raise ValueError(
                f"Step sequence numbers must be continuous starting from 1. "
                f"Expected {expected_numbers}, got {step_numbers}"
            )

        return v

    model_config = ConfigDict(from_attributes=True)


class BatchOperationRequest(BaseModel):
    """Schema for batch operations on test cases"""
    case_ids: List[str] = Field(..., min_length=1, description="List of test case IDs")
    action: str = Field(..., pattern="^(delete|finalize|unfinalize|update_priority|update_automation_status|mark_hallucination)$")
    params: Optional[Dict[str, Any]] = Field(None, description="Additional parameters for the action")

    @model_validator(mode='after')
    def validate_action_params(self) -> 'BatchOperationRequest':
        """Validate that required params are provided for specific actions"""
        action = self.action
        params = self.params or {}

        if action == "update_priority" and "priority" not in params:
            raise ValueError("'priority' is required in params for update_priority action")

        if action == "update_priority" and params.get("priority") not in ["P0", "P1", "P2", "P3"]:
            raise ValueError("priority must be one of: P0, P1, P2, P3")

        if action == "update_automation_status" and "automation_status" not in params:
            raise ValueError("'automation_status' is required in params for update_automation_status action")

        if action == "update_automation_status" and params.get("automation_status") not in list(AUTOMATION_STATUSES):
            raise ValueError(f"automation_status must be one of: {', '.join(AUTOMATION_STATUSES)}")

        if action == "mark_hallucination" and "hallucination_status" not in params:
            raise ValueError("'hallucination_status' is required in params for mark_hallucination action")

        if action == "mark_hallucination" and params.get("hallucination_status") not in list(HALLUCINATION_STATUSES):
            raise ValueError(f"hallucination_status must be one of: {', '.join(HALLUCINATION_STATUSES)}")

        return self

    model_config = ConfigDict(from_attributes=True)


class CaseResponse(BaseModel):
    """Schema for test case response (basic info)"""
    id: str
    project_id: str
    point_id: Optional[str] = None
    point_name: Optional[str] = None
    name: str
    priority: str
    case_type: str
    automation_status: str
    expected_result: str
    is_finalized: bool
    version: int
    hallucination_status: str
    created_by: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class CaseDetailResponse(BaseModel):
    """Schema for detailed test case response (includes all fields)"""
    id: str
    project_id: str
    point_id: Optional[str] = None
    name: str
    priority: str
    case_type: str
    automation_status: str
    precondition: Optional[str] = None
    steps: List[StepSchema]
    expected_result: str
    is_finalized: bool
    version: int
    hallucination_status: str
    created_by: Optional[str] = None
    created_at: str
    updated_at: str
    is_deleted: bool

    model_config = ConfigDict(from_attributes=True)


class CaseListResponse(BaseModel):
    """Schema for test case list response with pagination"""
    total: int = Field(..., description="Total number of test cases")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    items: List[CaseResponse] = Field(..., description="List of test cases")

    model_config = ConfigDict(from_attributes=True)


class CaseStatsResponse(BaseModel):
    """Schema for test case statistics response"""
    total_cases: int = Field(0, description="Total number of test cases")
    by_priority: Dict[str, int] = Field(default_factory=dict, description="Count by priority")
    by_case_type: Dict[str, int] = Field(default_factory=dict, description="Count by case type")
    by_automation_status: Dict[str, int] = Field(default_factory=dict, description="Count by automation status")
    finalized_count: int = Field(0, description="Number of finalized cases")
    hallucination_count: int = Field(0, description="Number of cases marked as hallucination")

    model_config = ConfigDict(from_attributes=True)
