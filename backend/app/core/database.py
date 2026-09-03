"""
Database configuration and session management
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Convert postgresql:// to postgresql+asyncpg://
DATABASE_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    # SQL 回显改由日志级别治理: SQLALCHEMY_LEVEL(默认 WARNING) 静默 SQL 刷屏。
    # echo=True 会绕过 logger 级别直接强制输出——这里固定 False，调试 SQL 时
    # 把 .env 的 SQLALCHEMY_LEVEL=DEBUG 即可。
    echo=False,
    poolclass=NullPool,  # Use NullPool for better compatibility
    pool_pre_ping=True,
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Alias kept for tasks/services that import AsyncSessionLocal
# (previously the only export name; both are now supported)
AsyncSessionLocal = async_session_maker

# Create declarative base
Base = declarative_base()


async def get_db() -> AsyncSession:
    """
    Dependency to get database session
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()


async def init_db():
    """
    Initialize database tables
    """
    async with engine.begin() as conn:
        # Import all models to ensure they are registered
        from app.models import project, test_case, element, execution
        from app.models import whitescan  # W9: code_scan/code_issue (test_case FK target)

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")
