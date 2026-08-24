"""
Test rule models
"""

from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
import uuid
from datetime import datetime


class TestRule(Base):
    """测试规则模型"""
    __tablename__ = "test_rule"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    prompt_template = Column(Text)
    is_builtin = Column(Boolean, default=False)
    status = Column(String(20), default="active")
    created_by = Column(String(50))
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
