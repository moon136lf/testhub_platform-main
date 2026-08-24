"""Test environment CRUD service."""
import logging
from typing import Optional, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import TestEnv

logger = logging.getLogger(__name__)


class TestEnvService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self) -> list:
        q = select(TestEnv).order_by(TestEnv.created_at.desc())
        rows = (await self.db.execute(q)).scalars().all()
        return [r.to_dict() for r in rows]

    async def get(self, env_id: str) -> Optional[dict]:
        q = select(TestEnv).where(TestEnv.id == env_id)
        row = (await self.db.execute(q)).scalar_one_or_none()
        return row.to_dict() if row else None

    async def create(self, data: Dict[str, Any]) -> dict:
        env = TestEnv(
            name=data["name"], url=data["url"], env_type=data.get("env_type", "dev"),
            status=data.get("status", "active"), credentials=data.get("credentials"),
            created_by=data.get("created_by", "system"),
        )
        self.db.add(env)
        await self.db.commit()
        await self.db.refresh(env)
        return env.to_dict()

    async def update(self, env_id: str, data: Dict[str, Any]) -> Optional[dict]:
        q = select(TestEnv).where(TestEnv.id == env_id)
        env = (await self.db.execute(q)).scalar_one_or_none()
        if not env:
            return None
        for f in ("name", "url", "env_type", "status", "credentials"):
            if f in data and data[f] is not None:
                setattr(env, f, data[f])
        await self.db.commit()
        await self.db.refresh(env)
        return env.to_dict()

    async def delete(self, env_id: str) -> bool:
        q = select(TestEnv).where(TestEnv.id == env_id)
        env = (await self.db.execute(q)).scalar_one_or_none()
        if not env:
            return False
        env.status = "inactive"  # soft delete
        await self.db.commit()
        return True
