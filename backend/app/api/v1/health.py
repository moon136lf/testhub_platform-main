"""
Health check endpoints
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db

router = APIRouter()


@router.get("/")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint
    """
    try:
        # Test database connection
        result = await db.execute(text("SELECT 1"))
        db_status = "healthy" if result else "unhealthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "healthy",
        "database": db_status
    }


@router.get("/ping")
async def ping():
    """
    Simple ping endpoint
    """
    return {"message": "pong"}
