"""Script conversion session model."""
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class ConvertSession(Base):
    """转脚本会话 - 一次批量转换任务"""
    __tablename__ = "convert_session"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    case_ids = Column(JSONB, nullable=False, comment="本次转换用例 ID 列表")
    ai_optimize = Column(Boolean, default=False, comment="未命中时是否调 AI 生成定位器")
    status = Column(String(20), default="active", comment="active/done/failed")
    progress = Column(Numeric(5, 2), default=0)
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "case_ids": self.case_ids,
            "ai_optimize": self.ai_optimize,
            "status": self.status,
            "progress": float(self.progress) if self.progress else 0,
            "tokens_used": self.tokens_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
