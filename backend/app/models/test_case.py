"""
Test case related models
"""

from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid

from app.core.database import Base


class TestPoint(Base):
    """Test point table"""

    __tablename__ = "test_point"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    page_name = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    type_label = Column(String(20), nullable=False)
    description = Column(String(500))
    source_ref = Column(String(500))
    status = Column(String(20), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "page_name": self.page_name,
            "name": self.name,
            "type_label": self.type_label,
            "description": self.description,
            "source_ref": self.source_ref,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TestCase(Base):
    """Test case table"""

    __tablename__ = "test_case"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_case_project_name"),
        Index("idx_test_case_project", "project_id"),
        Index("idx_test_case_automation", "automation_status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    point_id = Column(UUID(as_uuid=True), ForeignKey("test_point.id", ondelete="SET NULL"))
    name = Column(String(100), nullable=False)
    priority = Column(String(2), nullable=False, default="P1")
    case_type = Column(String(20), nullable=False, default="functional")
    automation_status = Column(String(20), default="pending")
    precondition = Column(Text)
    steps = Column(JSONB, nullable=False)
    expected_result = Column(String(200), nullable=False)
    is_finalized = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    hallucination_status = Column(String(20), default="normal")
    created_by = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, default=False)

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "point_id": str(self.point_id) if self.point_id else None,
            "name": self.name,
            "priority": self.priority,
            "case_type": self.case_type,
            "automation_status": self.automation_status,
            "precondition": self.precondition,
            "steps": self.steps,
            "expected_result": self.expected_result,
            "is_finalized": self.is_finalized,
            "version": self.version,
            "hallucination_status": self.hallucination_status,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted
        }


class ScriptAsset(Base):
    """Script asset table"""

    __tablename__ = "script_asset"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    status = Column(String(20), default="generated")
    category = Column(String(20), default="uncategorized")
    module = Column(String(50))
    last_status = Column(String(20), default="never_run")
    run_count = Column(Integer, default=0)
    last_run_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "case_id": str(self.case_id),
            "content": self.content,
            "version": self.version,
            "status": self.status,
            "category": self.category,
            "module": self.module,
            "last_status": self.last_status,
            "run_count": self.run_count,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CaseVersion(Base):
    """Test case version history (snapshot on each update)."""
    __tablename__ = "case_version"
    __table_args__ = (
        Index("idx_case_version_case", "case_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False, comment="用例变更前完整快照")
    diff_summary = Column(Text, comment="与上一版变化字段摘要")
    changed_by = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "case_id": str(self.case_id),
            "version": self.version,
            "snapshot": self.snapshot,
            "diff_summary": self.diff_summary,
            "changed_by": self.changed_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
