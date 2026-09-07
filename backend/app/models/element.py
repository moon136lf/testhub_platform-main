"""
Element repository models
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid

from app.core.database import Base


class PageRepository(Base):
    """Page repository table"""

    __tablename__ = "page_repository"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True)
    page_name = Column(String(100), nullable=False, comment="页面名称")
    page_url = Column(String(500), nullable=False, comment="页面URL")
    screenshot_url = Column(Text, comment="页面截图URL (MinIO)")
    parent_id = Column(UUID(as_uuid=True), ForeignKey("page_repository.id", ondelete="SET NULL"), nullable=True, index=True, comment="父页面 ID（页面树层级，NULL=顶级）")
    element_count = Column(Integer, default=0, comment="该页面下元素数量")
    sort_order = Column(Integer, default=0, comment="同级排序号，上移下移改此值")
    last_fetch_at = Column(DateTime(timezone=True), comment="最后一次抓取时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String(50), default="system")

    # Relationships (lazy="selectin" is async-safe for AsyncSession)
    elements = relationship("ElementRepository", back_populates="page", cascade="all, delete-orphan", lazy="selectin")
    fetch_histories = relationship("FetchHistory", back_populates="page", cascade="all, delete-orphan", lazy="selectin")

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "page_name": self.page_name,
            "page_url": self.page_url,
            "screenshot_url": self.screenshot_url,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "sort_order": self.sort_order or 0,
            "element_count": self.element_count,
            "last_fetch_at": self.last_fetch_at.isoformat() if self.last_fetch_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ElementRepository(Base):
    """Element repository table"""

    __tablename__ = "element_repository"
    __table_args__ = (
        UniqueConstraint("page_id", "element_id", name="uq_element_repository_page_element"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(UUID(as_uuid=True), ForeignKey("page_repository.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True)

    # Element identification
    element_id = Column(String(100), nullable=False, index=True, comment="元素唯一标识")
    element_name = Column(String(100), comment="元素名称（用户可编辑）")
    element_type = Column(String(50), nullable=False, comment="button/input/link/select/other")
    element_text = Column(String(200), comment="元素显示文本")

    # Locator strategies chain (core field)
    locator_strategies = Column(JSONB, nullable=False, comment="多层定位器数组")

    # Semantic info (for self-healing)
    semantic_info = Column(JSONB, comment="元素语义信息")

    # Element position
    position_x = Column(Integer, comment="元素X坐标")
    position_y = Column(Integer, comment="元素Y坐标")
    width = Column(Integer, comment="元素宽度")
    height = Column(Integer, comment="元素高度")

    # Element attributes
    attributes = Column(JSONB, comment="元素HTML属性")

    # Status management
    status = Column(String(20), default="active", comment="active/deprecated/deleted")
    scope = Column(String(20), default="page", comment="page=页面级 global=全局共享")
    recycled_at = Column(DateTime(timezone=True), comment="软删时间，30天可恢复")
    confidence = Column(Integer, default=0, comment="置信度 0-10")
    source = Column(String(20), default="manual", comment="manual/auto/healed/ai_fixed")

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String(50), default="system")
    last_verified_at = Column(DateTime(timezone=True), comment="最后验证时间")

    # Relationships
    page = relationship("PageRepository", back_populates="elements", lazy="selectin")

    def to_dict(self):
        return {
            "id": str(self.id),
            "page_id": str(self.page_id),
            "project_id": str(self.project_id),
            "element_id": self.element_id,
            "element_name": self.element_name,
            "element_type": self.element_type,
            "element_text": self.element_text,
            "locator_strategies": self.locator_strategies,
            "semantic_info": self.semantic_info,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "width": self.width,
            "height": self.height,
            "attributes": self.attributes,
            "status": self.status,
            "scope": self.scope or "page",
            "recycled_at": self.recycled_at.isoformat() if self.recycled_at else None,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else None,
        }


class FetchHistory(Base):
    """Fetch history table"""

    __tablename__ = "fetch_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(UUID(as_uuid=True), ForeignKey("page_repository.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True)

    fetch_time = Column(DateTime(timezone=True), server_default=func.now(), comment="抓取时间")
    elements_found = Column(Integer, default=0, comment="发现的元素数量")
    elements_imported = Column(Integer, default=0, comment="实际入库的元素数量")
    screenshot_url = Column(String(500), comment="本次抓取的截图URL")

    # Fetch configuration
    fetch_url = Column(String(500), comment="抓取的URL")
    used_login = Column(Boolean, default=False, comment="是否使用了登录")

    # Execution result
    status = Column(String(20), default="success", comment="success/failed/partial")
    error_message = Column(Text, comment="失败时的错误信息")
    duration_seconds = Column(Integer, comment="抓取耗时（秒）")

    created_by = Column(String(50), default="system")

    # Relationships
    page = relationship("PageRepository", back_populates="fetch_histories", lazy="selectin")

    def to_dict(self):
        return {
            "id": str(self.id),
            "page_id": str(self.page_id),
            "project_id": str(self.project_id),
            "fetch_time": self.fetch_time.isoformat() if self.fetch_time else None,
            "elements_found": self.elements_found,
            "elements_imported": self.elements_imported,
            "screenshot_url": self.screenshot_url,
            "fetch_url": self.fetch_url,
            "used_login": self.used_login,
            "status": self.status,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
        }


class ChangeDetection(Base):
    """Change detection table - 一次抓取对比的聚合记录（ELEM-05/06/07）"""

    __tablename__ = "change_detection"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(UUID(as_uuid=True), ForeignKey("page_repository.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True)

    # 对比基准：base（上一次）与 current（本次）抓取记录
    base_fetch_id = Column(UUID(as_uuid=True), ForeignKey("fetch_history.id", ondelete="SET NULL"), comment="基准抓取历史ID")
    current_fetch_id = Column(UUID(as_uuid=True), ForeignKey("fetch_history.id", ondelete="SET NULL"), comment="当前抓取历史ID")

    check_time = Column(DateTime(timezone=True), server_default=func.now(), comment="检测时间")

    # 聚合字段：三类变更（ELEM-05）
    added = Column(JSONB, default=list, comment="新增元素列表 [{element_id, element_name, locator}]")
    removed = Column(JSONB, default=list, comment="消失元素列表 [{element_id, element_name, locator}]")
    modified = Column(JSONB, default=list, comment="变更元素列表 [{element_id, element_name, old_locator, new_locator}]")

    # 统计计数
    added_count = Column(Integer, default=0, comment="新增数量")
    removed_count = Column(Integer, default=0, comment="消失数量")
    modified_count = Column(Integer, default=0, comment="变更数量")

    # 影响分析（ELEM-06）
    affected_scripts = Column(JSONB, default=list, comment="受影响的脚本列表 [{script_id, script_name, elements:[...]}]")
    affected_script_count = Column(Integer, default=0, comment="受影响脚本数量")
    impact_level = Column(String(20), default="low", comment="low/medium/high")

    # 处理状态（ELEM-07 一键更新定位器后流转）
    status = Column(String(20), default="pending", comment="pending/reviewed/fixed")
    reviewed_by = Column(String(50), comment="审核人")
    reviewed_at = Column(DateTime(timezone=True), comment="审核时间")
    fixed_at = Column(DateTime(timezone=True), comment="一键更新定位器完成时间")

    def to_dict(self):
        return {
            "id": str(self.id),
            "page_id": str(self.page_id),
            "project_id": str(self.project_id) if self.project_id else None,
            "base_fetch_id": str(self.base_fetch_id) if self.base_fetch_id else None,
            "current_fetch_id": str(self.current_fetch_id) if self.current_fetch_id else None,
            "check_time": self.check_time.isoformat() if self.check_time else None,
            "added": self.added or [],
            "removed": self.removed or [],
            "modified": self.modified or [],
            "added_count": self.added_count or 0,
            "removed_count": self.removed_count or 0,
            "modified_count": self.modified_count or 0,
            "affected_scripts": self.affected_scripts or [],
            "affected_script_count": self.affected_script_count or 0,
            "impact_level": self.impact_level,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "fixed_at": self.fixed_at.isoformat() if self.fixed_at else None,
        }


class SelfHealCache(Base):
    """自愈缓存表 (§8.2.8) - 记录元素定位器的自愈历史与置信度"""

    __tablename__ = "self_heal_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    element_id = Column(String(100), nullable=False, index=True, comment="关联元素的 element_id（业务标识）")
    element_db_id = Column(UUID(as_uuid=True), ForeignKey("element_repository.id", ondelete="CASCADE"), nullable=True, index=True, comment="关联元素记录ID")

    # 自愈后的定位器（成功自愈时回写的定位器）
    healed_locator = Column(JSONB, nullable=False, comment="自愈定位器 {type, value, score}")
    heal_strategy = Column(String(50), comment="自愈策略：semantic/coords/text/aria")

    # 置信度（命中+1，失效-1，连续3次失败删除）
    confidence = Column(Integer, default=0, comment="置信度，命中+1/失效-1，>=3 回写仓库")
    success_count = Column(Integer, default=0, comment="成功命中次数")
    failure_count = Column(Integer, default=0, comment="连续失败次数（成功时归零）")

    # 原始定位器（失败时的参考）
    original_locator = Column(JSONB, comment="原失败定位器")

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_used_at = Column(DateTime(timezone=True), comment="最后使用时间")

    def to_dict(self):
        return {
            "id": str(self.id),
            "element_id": self.element_id,
            "element_db_id": str(self.element_db_id) if self.element_db_id else None,
            "healed_locator": self.healed_locator,
            "heal_strategy": self.heal_strategy,
            "confidence": self.confidence,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "original_locator": self.original_locator,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }
