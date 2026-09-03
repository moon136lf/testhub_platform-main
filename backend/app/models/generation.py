"""
Generation session models
"""

from sqlalchemy import Column, String, Text, Integer, Boolean, TIMESTAMP, ForeignKey, text as sa_text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.core.database import Base
import uuid


class GenerationSession(Base):
    """生成会话模型"""
    __tablename__ = "generation_session"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id"))
    document_content = Column(Text)
    selected_rules = Column(JSONB)
    selected_knowledge = Column(JSONB)
    hallucination_strategy = Column(String(20))
    current_step = Column(Integer, default=1)
    status = Column(String(20), default="active")
    # UTC 时间由 DB 生成（now() 带 DB 时区）；前端按 ISO 字符串展示
    created_at = Column(TIMESTAMP, server_default=sa_text("now()"))
    updated_at = Column(TIMESTAMP, server_default=sa_text("now()"))


class HallucinationConfig(Base):
    """幻觉检测配置模型"""
    __tablename__ = "hallucination_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config_type = Column(String(50), nullable=False)
    config_value = Column(Text, nullable=False)
    description = Column(String(200))
    is_enabled = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=sa_text("now()"))
