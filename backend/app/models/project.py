"""
Project model
"""

from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class Project(Base):
    """Project table"""

    __tablename__ = "project"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False)
    code = Column(String(20), nullable=False, unique=True)
    description = Column(String(500))
    target_url = Column(String(500), nullable=False, default="http://localhost:81")
    status = Column(String(10), default="active")
    created_by = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_deleted = Column(Boolean, default=False)

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": str(self.id),
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "target_url": self.target_url,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted
        }
