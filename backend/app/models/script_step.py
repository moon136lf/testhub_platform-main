"""ScriptStep 模型（方案V1 阶段4）：可视化步骤表=脚本本体，行落库支持用例溯源。"""
import uuid

from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class ScriptStep(Base):
    __tablename__ = "script_steps"
    __table_args__ = (
        UniqueConstraint("script_id", "step_no", name="uq_script_step_no"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    script_id = Column(UUID(as_uuid=True), ForeignKey("script_asset.id", ondelete="CASCADE"), nullable=False, index=True)
    step_no = Column(Integer, nullable=False, comment="步骤序号(1起)")
    case_step_no = Column(Integer, comment="溯源：用例步骤号，可空")
    action = Column(String(30), nullable=False)
    element_id = Column(UUID(as_uuid=True), ForeignKey("element_repository.id", ondelete="SET NULL"), nullable=True)
    extra_element_id = Column(UUID(as_uuid=True), ForeignKey("element_repository.id", ondelete="SET NULL"), nullable=True, comment="辅元素(识别验证码:源图)")
    target = Column(String(500), default="", comment="定位符快照(元素改版不影响已生成脚本)")
    value = Column(Text, default="")
    assertion = Column(Text, default="", comment="期望值")
    assertion_type = Column(String(30), default="", comment="expect_text/expect_url/expect_value/expect_attribute/expect_toast")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
