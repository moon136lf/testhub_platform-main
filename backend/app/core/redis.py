"""
Redis client configuration
"""

import redis.asyncio as aioredis
from typing import Optional
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis client wrapper"""

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None

    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("Redis connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def close(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")

    async def get(self, key: str) -> Optional[str]:
        """Get value by key"""
        return await self.redis.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None):
        """Set key-value pair with optional expiration"""
        await self.redis.set(key, value, ex=ex)

    async def delete(self, key: str):
        """Delete key"""
        await self.redis.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        return await self.redis.exists(key) > 0

    async def hset(self, name: str, key: str, value: str):
        """Set hash field"""
        await self.redis.hset(name, key, value)

    async def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field"""
        return await self.redis.hget(name, key)

    async def hgetall(self, name: str) -> dict:
        """Get all hash fields"""
        return await self.redis.hgetall(name)


# Global Redis client instance
redis_client = RedisClient()
