"""
Test rule schemas
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class TestRuleBase(BaseModel):
    """测试规则基础模型"""
    name: str = Field(..., max_length=50, description="规则名称")
    description: str = Field(..., description="规则描述")
    prompt_template: Optional[str] = Field(None, description="提示词模板")


class TestRuleCreate(TestRuleBase):
    """创建测试规则请求"""
    created_by: Optional[str] = Field(None, max_length=50, description="创建人")


class TestRuleUpdate(BaseModel):
    """更新测试规则请求"""
    name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    prompt_template: Optional[str] = None
    status: Optional[str] = Field(None, max_length=20)


class TestRuleResponse(TestRuleBase):
    """测试规则响应"""
    id: UUID
    is_builtin: bool
    status: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
