"""
Database initialization script
"""

import asyncio
import logging
from sqlalchemy import text

from app.core.database import engine, Base
from app.models import (
    Project,
    TestPoint,
    TestCase,
    ScriptAsset,
    CaseVersion,
    PageRepository,
    ElementRepository,
    FetchHistory,
    ChangeDetection,
    SelfHealCache,
    ExecutionRecord,
    AICallLog,
    KnowledgeDocument,
    KnowledgeChunk,
    TestRule,
    GenerationSession,
    HallucinationConfig,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_database():
    """Initialize database tables"""
    logger.info("Creating database tables...")

    async with engine.begin() as conn:
        # Drop all tables (for development)
        # await conn.run_sync(Base.metadata.drop_all)
        # logger.info("Dropped existing tables")

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Created all tables")

        # Enable pgvector extension
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            logger.info("Enabled pgvector extension")
        except Exception as e:
            logger.warning(f"Could not enable pgvector: {e}")

        # Insert default project if not exists
        result = await conn.execute(
            text("SELECT COUNT(*) FROM project WHERE code = 'DEFAULT'")
        )
        count = result.scalar()

        if count == 0:
            await conn.execute(
                text("""
                    INSERT INTO project (name, code, description, target_url, created_by)
                    VALUES ('默认项目', 'DEFAULT', 'MoonTest默认测试项目',
                            'http://localhost:81', 'system')
                """)
            )
            logger.info("Created default project")
        else:
            logger.info("Default project already exists")

    logger.info("Database initialization completed!")


if __name__ == "__main__":
    asyncio.run(init_database())
