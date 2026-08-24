"""SystemSettingService tests."""
import time
import pytest
from unittest.mock import AsyncMock, Mock

from app.services.system_setting_service import SystemSettingService, _settings_cache


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = Mock()
    db.refresh = AsyncMock()
    _settings_cache.clear()  # reset cache between tests
    return db


class TestGetSet:
    @pytest.mark.asyncio
    async def test_get_plain_value(self, mock_db):
        row = Mock()
        row.id = "id1"; row.category = "runtime"; row.key = "heal.strategy"
        row.value = "SMART"; row.value_encrypted = None
        row.value_type = "string"; row.is_secret = False
        row.description = None; row.updated_by = None; row.updated_at = None
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row))

        svc = SystemSettingService(mock_db)
        val = await svc.get("heal.strategy")
        assert val == "SMART"

    @pytest.mark.asyncio
    async def test_get_secret_value_decrypts(self, mock_db):
        from app.core.security import encrypt_value
        cipher = encrypt_value("sk-real-key")
        row = Mock()
        row.id = "id2"; row.category = "ai"; row.key = "glm-4.api_key"
        row.value = None; row.value_encrypted = cipher
        row.value_type = "string"; row.is_secret = True
        row.description = None; row.updated_by = None; row.updated_at = None
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row))

        svc = SystemSettingService(mock_db)
        val = await svc.get("glm-4.api_key")
        assert val == "sk-real-key"

    @pytest.mark.asyncio
    async def test_get_missing_returns_default(self, mock_db):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = SystemSettingService(mock_db)
        assert await svc.get("no.such.key", default="fallback") == "fallback"

    @pytest.mark.asyncio
    async def test_set_plain_persists_and_invalidates_cache(self, mock_db):
        # cache has stale value
        _settings_cache.set(("runtime", "heal.strategy"), "OLD", time.time() + 60)
        row = Mock()
        row.id = "id1"; row.category = "runtime"; row.key = "heal.strategy"
        row.value = "OLD"; row.value_encrypted = None
        row.value_type = "string"; row.is_secret = False
        row.description = None; row.updated_by = None; row.updated_at = None
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=row))

        svc = SystemSettingService(mock_db)
        await svc.set("runtime", "heal.strategy", "SMART", value_type="string", updated_by="admin")

        # cache entry for this key removed
        assert ("runtime", "heal.strategy") not in _settings_cache
        # row value updated + committed
        assert row.value == "SMART"
        assert row.is_secret is False
        assert mock_db.commit.called


class TestCache:
    @pytest.mark.asyncio
    async def test_cache_hits_avoid_db(self, mock_db):
        # prime cache
        _settings_cache.set(("runtime", "heal.strategy"), "SMART", time.time() + 60)
        svc = SystemSettingService(mock_db)
        val = await svc.get("heal.strategy", category="runtime")
        assert val == "SMART"
        # db.execute NOT called (cache hit)
        assert not mock_db.execute.called
