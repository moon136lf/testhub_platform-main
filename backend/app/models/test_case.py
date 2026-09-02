"""
Test case related models
"""

from sqlalchemy import Column, String, Boolean, DateTime, Text, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid

from app.core.database import Base


class TestPoint(Base):
    """Test point table"""

    __tablename__ = "test_point"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    page_name = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    type_label = Column(String(20), nullable=False)
    description = Column(String(500))
    source_ref = Column(String(500))
    status = Column(String(20), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "page_name": self.page_name,
            "name": self.name,
            "type_label": self.type_label,
            "description": self.description,
            "source_ref": self.source_ref,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TestCase(Base):
    """Test case table"""

    __tablename__ = "test_case"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_case_project_name"),
        Index("idx_test_case_project", "project_id"),
        Index("idx_test_case_automation", "automation_status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False)
    point_id = Column(UUID(as_uuid=True), ForeignKey("test_point.id", ondelete="SET NULL"))
    name = Column(String(100), nullable=False)
    priority = Column(String(2), nullable=False, default="P1")
    case_type = Column(String(20), nullable=False, default="functional")
    automation_status = Column(String(20), default="pending")
    precondition = Column(Text)
    steps = Column(JSONB, nullable=False)
    expected_result = Column(String(200), nullable=False)
    is_finalized = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    hallucination_status = Column(String(20), default="normal")
    created_by = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # W5: review & refinement
    review_status = Column(String(20), default="pending", comment="pending/passed/needs_revision")
    review_comment = Column(Text, comment="评审意见")
    feasibility_level = Column(String(20), comment="full/partial/manual")
    cannot_automate_reason = Column(String(200), comment="不可自动化原因")
    refinement_report = Column(JSONB, comment="精修报告 JSON")
    refined_at = Column(DateTime(timezone=True), comment="最后精修时间")
    is_deleted = Column(Boolean, default=False)
    # W9: whitescan regression case source (NULL = not whitescan-generated)
    source_issue_id = Column(UUID(as_uuid=True), ForeignKey("code_issue.id", ondelete="SET NULL"), nullable=True)
    # 批次归属（用例管理记录层, case_batch.id）; NULL=历史遗留(将被清理)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("case_batch.id", ondelete="SET NULL"), nullable=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "point_id": str(self.point_id) if self.point_id else None,
            "name": self.name,
            "priority": self.priority,
            "case_type": self.case_type,
            "automation_status": self.automation_status,
            "precondition": self.precondition,
            "steps": self.steps,
            "expected_result": self.expected_result,
            "is_finalized": self.is_finalized,
            "version": self.version,
            "hallucination_status": self.hallucination_status,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "review_status": self.review_status,
            "review_comment": self.review_comment,
            "feasibility_level": self.feasibility_level,
            "cannot_automate_reason": self.cannot_automate_reason,
            "refinement_report": self.refinement_report,
            "refined_at": self.refined_at.isoformat() if self.refined_at else None,
            "is_deleted": self.is_deleted
        }


class ScriptAsset(Base):
    """Script asset table"""

    __tablename__ = "script_asset"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_script_asset_project_name"),
        Index("idx_script_asset_project", "project_id"),
        Index("idx_script_asset_case", "case_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    # #4: script library fields (req 3.6.3.3 / 3.6.5)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, comment="脚本名称（继承用例名）")
    description = Column(String(500), comment="脚本说明")
    step_mapping = Column(JSONB, comment="skill Step4 步骤对照表")
    locator_source = Column(String(20), default="none_draft", comment="element_library/ai_generated/mixed/none_draft")
    ai_diagnosis = Column(JSONB, comment="调试修复诊断卡")
    status = Column(String(20), default="generated")
    category = Column(String(20), default="uncategorized")
    module = Column(String(50))
    last_status = Column(String(20), default="never_run")
    run_count = Column(Integer, default=0)
    last_run_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    @property
    def diagnosis_list(self) -> list:
        """诊断卡数组视图 (#5c): 兼容 #4 旧单对象 dict 格式."""
        if not self.ai_diagnosis:
            return []
        if isinstance(self.ai_diagnosis, dict):
            return [self.ai_diagnosis]
        return self.ai_diagnosis

    def append_diagnosis(self, card: dict, mode: str) -> None:
        """append 诊断卡 (rule/multimodal), 补 mode + created_at, 保留历史."""
        from datetime import datetime as _dt
        card = dict(card)
        card.setdefault("mode", mode)
        card.setdefault("created_at", _dt.utcnow().isoformat())
        existing = self.diagnosis_list
        # 旧 dict 卡若无 mode, 视为 #4 rule 卡
        for c in existing:
            if isinstance(c, dict) and "mode" not in c:
                c["mode"] = "rule"
        existing.append(card)
        self.ai_diagnosis = existing

    def to_dict(self):
        return {
            "id": str(self.id),
            "case_id": str(self.case_id),
            "content": self.content,
            "version": self.version,
            "project_id": str(self.project_id),
            "name": self.name,
            "description": self.description,
            "step_mapping": self.step_mapping,
            "locator_source": self.locator_source,
            "ai_diagnosis": self.ai_diagnosis,
            "status": self.status,
            "category": self.category,
            "module": self.module,
            "last_status": self.last_status,
            "run_count": self.run_count,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CaseVersion(Base):
    """Test case version history (snapshot on each update)."""
    __tablename__ = "case_version"
    __table_args__ = (
        Index("idx_case_version_case", "case_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot = Column(JSONB, nullable=False, comment="用例变更前完整快照")
    diff_summary = Column(Text, comment="与上一版变化字段摘要")
    changed_by = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "case_id": str(self.case_id),
            "version": self.version,
            "snapshot": self.snapshot,
            "diff_summary": self.diff_summary,
            "changed_by": self.changed_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
