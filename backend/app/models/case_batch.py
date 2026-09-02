"""
Case batch model — 用例生成批次（用例管理记录层）
"""

import uuid

from sqlalchemy import Column, String, Integer, ForeignKey, Index, UniqueConstraint, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base


class CaseBatch(Base):
    """用例生成批次"""
    __tablename__ = "case_batch"
    __table_args__ = (
        UniqueConstraint("project_id", "batch_name", name="uq_case_batch_project_name"),
        Index("idx_case_batch_project", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    batch_name = Column(String(200), nullable=False)
    batch_type = Column(String(20), nullable=False)  # whitescan_api/whitescan_ui/ai_generate/manual
    source_id = Column(UUID(as_uuid=True), nullable=True)  # scan_id / generation_session_id
    case_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "batch_name": self.batch_name,
            "batch_type": self.batch_type,
            "source_id": str(self.source_id) if self.source_id else None,
            "case_count": self.case_count or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
