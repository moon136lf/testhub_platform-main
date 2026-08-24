"""
System settings models: KV config, test env, token quota, operation log.
"""
import uuid

from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, ForeignKey, UniqueConstraint, Index, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class SystemSetting(Base):
    """KV configuration store. category = ai | runtime. Secrets encrypted."""
    __tablename__ = "system_setting"
    __table_args__ = (
        UniqueConstraint("category", "key", name="uq_system_setting_category_key"),
        Index("idx_system_setting_category", "category"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category = Column(Enum("ai", "runtime", name="system_setting_category", native_enum=False), nullable=False)  # ai / runtime
    key = Column(String(100), nullable=False)
    value = Column(Text)
    value_encrypted = Column(Text)
    value_type = Column(String(20), default="string")  # string/int/float/bool/json
    is_secret = Column(Boolean, default=False)
    description = Column(String(500))
    updated_by = Column(String(50))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self, reveal_secret: bool = False) -> dict:
        from app.core.security import decrypt_value
        if self.is_secret:
            shown = None
            if reveal_secret and self.value_encrypted:
                try:
                    shown = decrypt_value(self.value_encrypted)
                except Exception:
                    shown = None
            return {
                "id": str(self.id), "category": self.category, "key": self.key,
                "value": shown if reveal_secret else "***",
                "value_type": self.value_type, "is_secret": True,
                "description": self.description,
                "updated_by": self.updated_by,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }
        return {
            "id": str(self.id), "category": self.category, "key": self.key,
            "value": self.value,
            "value_type": self.value_type, "is_secret": False,
            "description": self.description,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TestEnv(Base):
    """Target test environment (dev/staging/prod)."""
    __tablename__ = "test_env"
    __table_args__ = (
        Index("idx_test_env_type", "env_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False)
    url = Column(String(500), nullable=False)
    env_type = Column(String(20), nullable=False, default="dev")  # dev/staging/prod
    status = Column(String(20), default="active")  # active/inactive
    credentials = Column(JSONB)  # encrypted-sensitive fields kept as JSON with encrypted values
    created_by = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self, reveal_secret: bool = False) -> dict:
        return {
            "id": str(self.id), "name": self.name, "url": self.url,
            "env_type": self.env_type, "status": self.status,
            "credentials": self.credentials or {},
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TokenQuota(Base):
    """Per-project token quota. `used` is aggregated from ai_call_log, not stored."""
    __tablename__ = "token_quota"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_token_quota_project"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    total_quota = Column(Integer, default=100000)
    alert_threshold = Column(Integer, default=10)  # percentage
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id), "project_id": str(self.project_id),
            "total_quota": self.total_quota, "alert_threshold": self.alert_threshold,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class OperationLog(Base):
    """Operation audit log."""
    __tablename__ = "operation_log"
    __table_args__ = (
        Index("idx_op_log_created", "created_at"),
        Index("idx_op_log_module", "module"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    target_type = Column(String(50))
    target_id = Column(String(100))
    detail = Column(JSONB)
    operator = Column(String(50))
    ip = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id), "module": self.module, "action": self.action,
            "target_type": self.target_type, "target_id": self.target_id,
            "detail": self.detail, "operator": self.operator, "ip": self.ip,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
