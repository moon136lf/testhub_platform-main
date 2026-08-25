"""
Execution related models
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, JSON, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class ExecutionRecord(Base):
    """Execution record table"""

    __tablename__ = "execution_record"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exec_id = Column(String(50), unique=True, nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    exec_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)
    total_cases = Column(Integer, default=0)
    passed_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    pass_rate = Column(Numeric(5, 2), default=0)
    duration_ms = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)
    env_info = Column(JSON)
    report_url = Column(Text)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))

    def to_dict(self):
        return {
            "id": str(self.id),
            "exec_id": self.exec_id,
            "project_id": str(self.project_id),
            "exec_type": self.exec_type,
            "status": self.status,
            "total_cases": self.total_cases,
            "passed_count": self.passed_count,
            "fail_count": self.fail_count,
            "pass_rate": float(self.pass_rate) if self.pass_rate else 0,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "env_info": self.env_info,
            "report_url": self.report_url,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class AICallLog(Base):
    """AI call log table"""

    __tablename__ = "ai_call_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    model = Column(String(50), nullable=False)
    tokens_used = Column(Integer, default=0)
    tokens_cost = Column(Numeric(10, 4), default=0)
    stage = Column(String(30), nullable=False)
    status = Column(String(20), default="success")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "model": self.model,
            "tokens_used": self.tokens_used,
            "tokens_cost": float(self.tokens_cost) if self.tokens_cost else 0,
            "stage": self.stage,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ExecutionDetail(Base):
    """执行明细表 - 每条用例/每步的执行记录 (§4 ER 图 1:N execution_record→execution_detail)"""
    __tablename__ = "execution_detail"
    __table_args__ = (
        Index("idx_exec_detail_record", "execution_record_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_record_id = Column(UUID(as_uuid=True), ForeignKey("execution_record.id", ondelete="CASCADE"), nullable=False)
    script_id = Column(UUID(as_uuid=True), ForeignKey("script_asset.id", ondelete="SET NULL"))
    case_id = Column(UUID(as_uuid=True), ForeignKey("test_case.id", ondelete="SET NULL"))
    step = Column(Integer, comment="步骤序号，0=整体")
    action = Column(String(50), comment="click/fill/select/.../overall")
    status = Column(String(20), nullable=False, comment="pass/fail/skip/pending")
    error_type = Column(String(30), comment="locate_failed/timeout/assertion_failed/script_error")
    error_msg = Column(Text)
    stack_trace = Column(Text)
    screenshot_url = Column(Text, comment="失败截图 MinIO URL")
    dom_snapshot = Column(Text, comment="失败时页面 DOM")
    heal_status = Column(String(20), default="none", comment="none/healing/healed/failed (#5b 用)")
    heal_log = Column(JSONB, comment="自愈日志数组 (#5b 用)")
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "execution_record_id": str(self.execution_record_id),
            "script_id": str(self.script_id) if self.script_id else None,
            "case_id": str(self.case_id) if self.case_id else None,
            "step": self.step,
            "action": self.action,
            "status": self.status,
            "error_type": self.error_type,
            "error_msg": self.error_msg,
            "stack_trace": self.stack_trace,
            "screenshot_url": self.screenshot_url,
            "dom_snapshot": self.dom_snapshot,
            "heal_status": self.heal_status,
            "heal_log": self.heal_log,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
