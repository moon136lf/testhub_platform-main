"""
Knowledge document schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class KnowledgeDocumentBase(BaseModel):
    """知识文档基础模型"""
    doc_name: str = Field(..., max_length=200, description="文档名称")
    doc_type: str = Field(..., max_length=20, description="文档类型: txt/docx/pdf/md")
    file_url: Optional[str] = Field(None, description="文件URL")
    content: Optional[str] = Field(None, description="文档内容")


class KnowledgeDocumentCreate(KnowledgeDocumentBase):
    """创建知识文档请求"""
    project_id: UUID = Field(..., description="项目ID")
    created_by: Optional[str] = Field(None, max_length=50, description="创建人")


class KnowledgeDocumentUpdate(BaseModel):
    """更新知识文档请求"""
    doc_name: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = None
    vector_status: Optional[str] = Field(None, max_length=20)


class KnowledgeDocumentResponse(KnowledgeDocumentBase):
    """知识文档响应"""
    id: UUID
    project_id: UUID
    chunk_count: int
    vector_status: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeChunkResponse(BaseModel):
    """知识分块响应"""
    id: UUID
    document_id: UUID
    chunk_index: int
    chunk_text: str
    created_at: datetime

    class Config:
        from_attributes = True
