"""
Generation session schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID


class GenerationSessionBase(BaseModel):
    """生成会话基础模型"""
    project_id: UUID = Field(..., description="项目ID")
    document_content: Optional[str] = Field(None, description="文档内容")
    selected_rules: Optional[Dict[str, Any]] = Field(None, description="选中的规则")
    selected_knowledge: Optional[Dict[str, Any]] = Field(None, description="选中的知识")
    hallucination_strategy: Optional[str] = Field(None, max_length=20, description="幻觉检测策略")


class GenerationSessionCreate(GenerationSessionBase):
    """创建生成会话请求"""
    pass


class GenerationSessionUpdate(BaseModel):
    """更新生成会话请求"""
    document_content: Optional[str] = None
    selected_rules: Optional[Dict[str, Any]] = None
    selected_knowledge: Optional[Dict[str, Any]] = None
    hallucination_strategy: Optional[str] = None
    current_step: Optional[int] = None
    status: Optional[str] = Field(None, max_length=20)


class GenerationSessionResponse(GenerationSessionBase):
    """生成会话响应"""
    id: UUID
    current_step: int
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HallucinationConfigBase(BaseModel):
    """幻觉检测配置基础模型"""
    config_type: str = Field(..., max_length=50, description="配置类型")
    config_value: str = Field(..., description="配置值")
    description: Optional[str] = Field(None, max_length=200, description="描述")


class HallucinationConfigCreate(HallucinationConfigBase):
    """创建幻觉检测配置请求"""
    pass


class HallucinationConfigResponse(HallucinationConfigBase):
    """幻觉检测配置响应"""
    id: UUID
    is_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True
