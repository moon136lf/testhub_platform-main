"""Whitescan models: code_scan + code_issue (req §5.1)."""
import uuid
from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class CodeScan(Base):
    """代码扫描记录"""

    __tablename__ = "code_scan"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True)
    repo_url = Column(String(500), nullable=False)
    branch = Column(String(100), default="main")
    status = Column(String(20), default="scanning", comment="scanning/done/failed")
    progress = Column(Integer, default=0, comment="扫描进度百分比 0-100（分阶段：10拉镜像/30 clone/30-90 semgrep/100 入库）")
    stage = Column(String(30), comment="当前阶段: pulling/clone/scanning/parsing")
    total_issues = Column(Integer, default=0)
    high_count = Column(Integer, default=0)
    mid_count = Column(Integer, default=0)
    low_count = Column(Integer, default=0)
    file_count = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    error_msg = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    issues = relationship("CodeIssue", back_populates="scan", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "repo_url": self.repo_url,
            "branch": self.branch,
            "status": self.status,
            "progress": self.progress or 0,
            "stage": self.stage,
            "total_issues": self.total_issues,
            "high_count": self.high_count,
            "mid_count": self.mid_count,
            "low_count": self.low_count,
            "file_count": self.file_count,
            "duration_ms": self.duration_ms,
            "error_msg": self.error_msg,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CodeIssue(Base):
    """代码问题"""

    __tablename__ = "code_issue"
    __table_args__ = (
        Index("idx_code_issue_scan", "scan_id"),
        Index("idx_code_issue_fingerprint", "fingerprint"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id = Column(UUID(as_uuid=True), ForeignKey("code_scan.id", ondelete="CASCADE"), nullable=False)
    severity = Column(String(10), nullable=False, comment="high/mid/low")
    file_path = Column(String(500), nullable=False)
    line_no = Column(Integer)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    ai_suggestion = Column(JSONB, comment="AI 修复建议：{suggestion, fixed_code, original_code}")
    example_code = Column(Text)
    status = Column(String(20), default="open", comment="open/fixed/false_positive")
    source_commit = Column(String(100))
    fingerprint = Column(String(200), comment="rule_id+file+line+code hash；误报忽略依据")
    case_outdated = Column(Boolean, default=False)
    handled_by = Column(String(50))
    handled_at = Column(DateTime(timezone=True))

    scan = relationship("CodeScan", back_populates="issues")

    def to_dict(self):
        return {
            "id": str(self.id),
            "scan_id": str(self.scan_id),
            "severity": self.severity,
            "file_path": self.file_path,
            "line_no": self.line_no,
            "title": self.title,
            "description": self.description,
            "ai_suggestion": self.ai_suggestion,
            "example_code": self.example_code,
            "status": self.status,
            "source_commit": self.source_commit,
            "fingerprint": self.fingerprint,
            "case_outdated": self.case_outdated,
            "handled_by": self.handled_by,
            "handled_at": self.handled_at.isoformat() if self.handled_at else None,
        }
