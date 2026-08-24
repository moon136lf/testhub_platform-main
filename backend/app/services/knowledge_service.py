"""
Knowledge Service - Vector search and document chunking
"""

import logging
from typing import List, Dict
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.services.ai_gateway import ai_gateway

logger = logging.getLogger(__name__)

# Chunking configuration
DEFAULT_CHUNK_SIZE = 500  # Optimal for embedding model context window
DEFAULT_OVERLAP = 50  # Ensures continuity between chunks


class KnowledgeService:
    """Knowledge service with vector search capabilities"""

    @staticmethod
    async def vectorize_document(db: AsyncSession, doc_id: UUID, content: str):
        """
        Vectorize a document by splitting into chunks and generating embeddings

        Args:
            db: Database session
            doc_id: Document ID
            content: Document content text

        Raises:
            Exception: If vectorization fails
        """
        try:
            logger.info(f"Starting vectorization for document {doc_id}")

            # Split text into chunks
            chunks = KnowledgeService._split_text(content)
            logger.info(f"Split document into {len(chunks)} chunks")

            # Generate embeddings for each chunk and store
            for idx, chunk_text in enumerate(chunks):
                # Generate embedding
                embedding = await ai_gateway.embed(chunk_text)

                # Create chunk record
                chunk = KnowledgeChunk(
                    document_id=doc_id,
                    chunk_index=idx,
                    chunk_text=chunk_text,
                    embedding=embedding
                )
                db.add(chunk)

            # Update document status
            result = await db.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
            )
            doc = result.scalar_one()
            doc.chunk_count = len(chunks)
            doc.vector_status = "completed"

            await db.commit()
            logger.info(f"Vectorization completed for document {doc_id}, {len(chunks)} chunks stored")

        except Exception as e:
            logger.error(f"Vectorization failed for document {doc_id}: {e}")
            await db.rollback()

            # Update document status to failed
            try:
                result = await db.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
                )
                doc = result.scalar_one()
                doc.vector_status = "failed"
                await db.commit()
            except Exception as update_error:
                logger.error(f"Failed to update document status: {update_error}")

            raise

    @staticmethod
    async def search_similar(
        db: AsyncSession,
        query: str,
        project_id: UUID,
        top_k: int = 10
    ) -> List[Dict]:
        """
        Search for similar document chunks using vector similarity

        Args:
            db: Database session
            query: Search query text
            project_id: Project ID to filter documents
            top_k: Number of top results to return (1-1000)

        Returns:
            List of dicts with: document_id, doc_name, doc_type, chunk_text, similarity

        Raises:
            ValueError: If top_k is out of valid range
        """
        # Validate top_k parameter
        if top_k <= 0 or top_k > 1000:
            raise ValueError("top_k must be between 1 and 1000")

        try:
            logger.info(f"Searching similar chunks for project {project_id}, query length: {len(query)}")

            # Generate query embedding
            query_embedding = await ai_gateway.embed(query)

            # Perform vector similarity search using pgvector
            sql = text("""
                SELECT
                    kd.id as document_id,
                    kd.doc_name,
                    kd.doc_type,
                    kc.chunk_text,
                    1 - (kc.embedding <=> CAST(:query_vector AS vector)) as similarity
                FROM knowledge_chunk kc
                JOIN knowledge_document kd ON kc.document_id = kd.id
                WHERE kd.project_id = :project_id
                  AND kd.vector_status = 'completed'
                ORDER BY kc.embedding <=> CAST(:query_vector AS vector)
                LIMIT :top_k
            """)

            result = await db.execute(
                sql,
                {
                    "query_vector": str(query_embedding),
                    "project_id": str(project_id),
                    "top_k": top_k
                }
            )

            rows = result.fetchall()
            results = [
                {
                    "document_id": str(row[0]),
                    "doc_name": row[1],
                    "doc_type": row[2],
                    "chunk_text": row[3],
                    "similarity": float(row[4])
                }
                for row in rows
            ]

            logger.info(f"Found {len(results)} similar chunks")
            return results

        except Exception as e:
            logger.error(f"Search similar failed: {e}")
            raise

    @staticmethod
    def _split_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> List[str]:
        """
        Split text into fixed-size chunks with overlap

        Args:
            text: Text to split
            chunk_size: Size of each chunk in characters
            overlap: Overlap between consecutive chunks in characters

        Returns:
            List of text chunks
        """
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)

            # Move start position for next chunk with overlap
            start = end - overlap

            # Prevent infinite loop if we're at the end
            if end >= len(text):
                break

        return chunks
