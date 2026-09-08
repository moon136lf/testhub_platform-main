"""Test set model — 阶段2 执行规划层（用例勾选集，来源 manual/ai_suggest/convert_page）"""
import uuid
from sqlalchemy import Column, String, Numeric, ForeignKey, UniqueConstraint, Index, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class TestSet(Base):
    """测试集"""
    __tablename__ = "test_set"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_set_project_name"),
        Index("idx_test_set_project", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    source = Column(String(20), nullable=False, default="manual")  # manual/ai_suggest/convert_page
    case_ids = Column(JSONB, nullable=False, default=list)
    description = Column(String(500))
    last_run_at = Column(DateTime(timezone=True))
    last_pass_rate = Column(Numeric(5, 2), default=0)
    last_exec_id = Column(String(50))
    status = Column(String(20), default="pending")  # pending/running/done
    created_by = Column(String(50), default="system")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "name": self.name,
            "source": self.source,
            "case_ids": self.case_ids or [],
            "description": self.description,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_pass_rate": float(self.last_pass_rate or 0),
            "last_exec_id": self.last_exec_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
