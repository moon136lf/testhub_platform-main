"""回归集关联表 (模块 #8, 需求 §3.6.5)."""
import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class RegressionSet(Base):
    """回归集关联表: 脚本 ↔ 回归集成员关系 + AI 识别结果 (REG-01/02)."""

    __tablename__ = "regression_set"
    __table_args__ = (
        UniqueConstraint("project_id", "script_id", name="uq_regression_project_script"),
        Index("idx_reg_project", "project_id"),
        Index("idx_reg_included", "actual_included"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"),
                        nullable=False, index=True)
    script_id = Column(UUID(as_uuid=True), ForeignKey("script_asset.id", ondelete="CASCADE"),
                       nullable=False)
    ai_suggested = Column(Boolean, default=False, comment="AI 判定是否纳入 (REG-02)")
    ai_reason = Column(String(200), comment="AI 命中原因 (规则名拼接, ≤200)")
    actual_included = Column(Boolean, default=False, comment="实际纳入 (AI建议+人工调整, REG-03)")
    include_source = Column(String(10), default="ai", comment="ai/manual")
    included_at = Column(DateTime(timezone=True), server_default=func.now())
