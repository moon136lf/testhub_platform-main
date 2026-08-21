"""Import/export schemas."""
from typing import List, Optional
from pydantic import BaseModel


class ImportResult(BaseModel):
    imported: int = 0
    failed: int = 0
    errors: List[dict] = []


class ExportParams(BaseModel):
    project_id: str
    format: str  # xlsx|json|xmind


class ImportParams(BaseModel):
    project_id: str
    format: str  # xlsx|csv|md
