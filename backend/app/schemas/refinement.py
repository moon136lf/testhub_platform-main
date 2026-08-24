"""Refinement report schemas."""
from typing import List, Optional, Any
from pydantic import BaseModel, Field


class Suggestion(BaseModel):
    id: str
    dimension: str  # 步骤完整性/断言增强/异常路径补充/数据准备清理/可行性修正
    severity: str = "medium"  # high/medium/low
    target_step: Optional[int] = None
    issue: str
    suggestion: str
    status: str = "pending"  # pending/applied/rejected


class Normativity(BaseModel):
    steps_complete: bool = True
    assertion_executable: bool = True
    precondition_complete: bool = True


class RefinementReport(BaseModel):
    score: int = Field(0, ge=0, le=100)
    refined_case: Optional[dict] = None
    suggestions: List[Suggestion] = []
    normativity: Normativity = Field(default_factory=Normativity)
    reuse_level: str = "new"  # new/duplicate/similar


class ApplySuggestionsRequest(BaseModel):
    """Request body for apply-suggestions.

    suggestion_ids = None means apply all pending suggestions.
    """
    suggestion_ids: Optional[List[str]] = None
