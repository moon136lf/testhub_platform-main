"""
Project schemas
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ProjectBase(BaseModel):
    """Base project schema"""
    name: str = Field(..., min_length=1, max_length=50)
    code: str = Field(..., min_length=1, max_length=20)
    description: Optional[str] = Field(None, max_length=500)
    target_url: str = Field(default="http://localhost:81", max_length=500)


class ProjectCreate(ProjectBase):
    """Project creation schema"""
    created_by: Optional[str] = Field(None, max_length=50)


class ProjectUpdate(BaseModel):
    """Project update schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    target_url: Optional[str] = Field(None, max_length=500)
    status: Optional[str] = Field(None, pattern="^(active|archived)$")


class ProjectResponse(ProjectBase):
    """Project response schema"""
    id: str
    status: str
    created_by: str
    created_at: str
    updated_at: str
    is_deleted: bool

    class Config:
        from_attributes = True
