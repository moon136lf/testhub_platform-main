"""System setting KV service with encryption + process cache."""
import time
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SystemSetting
from app.core.security import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)

_CACHE_TTL = 30  # seconds


class _SettingCache(dict):
    """Process cache mapping (category, key) -> (value, expiry_ts).

    Supports dict ops (get/pop/__contains__/clear) plus a convenience
    `set(key, value, expiry)` used by tests and bulk priming.
    """

    def set(self, key, value, expiry_ts):
        self[key] = (value, expiry_ts)


# Module-level process cache: (category, key) -> (value, expiry_ts)
_settings_cache: _SettingCache = _SettingCache()


class SystemSettingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, key: str, *, category: Optional[str] = None, default=None):
        """Get a setting value (decrypted if secret). Uses process cache (30s TTL)."""
        cat = category or self._guess_category(key)
        cached = _settings_cache.get((cat, key))
        if cached and cached[1] > time.time():
            return cached[0]

        row = await self._fetch_row(cat, key)
        if not row:
            return default
        val = self._read_value(row)
        _settings_cache[(cat, key)] = (val, time.time() + _CACHE_TTL)
        return val

    async def list(self, category: str):
        """List settings in a category (secrets masked)."""
        q = select(SystemSetting).where(SystemSetting.category == category)
        rows = (await self.db.execute(q)).scalars().all()
        return [r.to_dict(reveal_secret=False) for r in rows]

    async def set(self, category: str, key: str, value, *,
                  value_type: str = "string", is_secret: bool = False,
                  description: Optional[str] = None, updated_by: Optional[str] = None):
        """Upsert a setting. Encrypts if is_secret. Invalidates cache for the key."""
        row = await self._fetch_row(category, key)
        if row is None:
            row = SystemSetting(category=category, key=key)
            self.db.add(row)
        if is_secret:
            row.value = None
            row.value_encrypted = encrypt_value(str(value))
        else:
            row.value = str(value)
            row.value_encrypted = None
        row.value_type = value_type
        row.is_secret = is_secret
        if description is not None:
            row.description = description
        if updated_by:
            row.updated_by = updated_by
        await self.db.commit()
        # invalidate cache
        _settings_cache.pop((category, key), None)
        return row

    async def delete(self, category: str, key: str) -> bool:
        row = await self._fetch_row(category, key)
        if not row:
            return False
        await self.db.delete(row)
        await self.db.commit()
        _settings_cache.pop((category, key), None)
        return True

    # ---- internals ----
    async def _fetch_row(self, category: str, key: str) -> Optional[SystemSetting]:
        q = select(SystemSetting).where(
            SystemSetting.category == category,
            SystemSetting.key == key,
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    def _read_value(self, row: SystemSetting):
        if row.is_secret and row.value_encrypted:
            try:
                return decrypt_value(row.value_encrypted)
            except Exception as e:
                logger.warning(f"Failed to decrypt setting {row.key}: {e}")
                return None
        # cast by value_type
        v = row.value
        if v is None:
            return None
        if row.value_type == "int":
            try: return int(v)
            except ValueError: return v
        if row.value_type == "float":
            try: return float(v)
            except ValueError: return v
        if row.value_type == "bool":
            return v.lower() in ("true", "1", "yes")
        return v

    def _guess_category(self, key: str) -> str:
        """Heuristic: ai.* keys -> ai, else runtime."""
        # provider keys like 'glm-4.api_key' or 'ai.default_provider'
        if key.startswith("ai.") or any(seg in key for seg in (".api_key", ".api_url")):
            return "ai"
        return "runtime"


def clear_cache():
    """Clear the whole process cache (used after bulk config changes)."""
    _settings_cache.clear()
