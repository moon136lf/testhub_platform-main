"""
Knowledge management models
"""

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
import uuid

from app.core.database import Base


class KnowledgeDocument(Base):
    """Knowledge document table"""

    __tablename__ = "knowledge_document"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="RESTRICT"))
    doc_name = Column(String(200), nullable=False)
    doc_type = Column(String(20), nullable=False)
    file_url = Column(Text)
    content = Column(Text)
    chunk_count = Column(Integer, default=0)
    vector_status = Column(String(20), default="pending")
    created_by = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id) if self.project_id else None,
            "doc_name": self.doc_name,
            "doc_type": self.doc_type,
            "file_url": self.file_url,
            "content": self.content,
            "chunk_count": self.chunk_count,
            "vector_status": self.vector_status,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KnowledgeChunk(Base):
    """Knowledge chunk table with vector embeddings"""

    __tablename__ = "knowledge_chunk"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_document.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(1536))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "document_id": str(self.document_id),
            "chunk_index": self.chunk_index,
            "chunk_text": self.chunk_text,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
