"""TestEnvService tests."""
import pytest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.services.test_env_service import TestEnvService


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = Mock()
    db.refresh = AsyncMock()
    return db


class TestEnvCRUD:
    @pytest.mark.asyncio
    async def test_list_returns_all(self, mock_db):
        e1 = Mock(); e1.to_dict = Mock(return_value={"id": "1", "name": "dev"})
        e2 = Mock(); e2.to_dict = Mock(return_value={"id": "2", "name": "staging"})
        mock_db.execute.return_value = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[e1, e2]))))
        svc = TestEnvService(mock_db)
        result = await svc.list()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_create_persists(self, mock_db):
        async def fake_refresh(obj):
            obj.id = uuid4()
        mock_db.refresh.side_effect = fake_refresh
        svc = TestEnvService(mock_db)
        env = await svc.create({"name": "dev-env", "url": "http://x", "env_type": "dev",
                                "status": "active", "credentials": {}, "created_by": "admin"})
        assert mock_db.add.called
        assert mock_db.commit.called
        assert env["name"] == "dev-env"

    @pytest.mark.asyncio
    async def test_update_applies_fields(self, mock_db):
        env = Mock()
        env.to_dict = Mock(return_value={"id": "1", "name": "new", "url": "http://y"})
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=env))
        svc = TestEnvService(mock_db)
        result = await svc.update("1", {"name": "new", "url": "http://y"})
        assert env.name == "new"
        assert env.url == "http://y"
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self, mock_db):
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = TestEnvService(mock_db)
        assert await svc.update("1", {"name": "x"}) is None

    @pytest.mark.asyncio
    async def test_delete_soft(self, mock_db):
        env = Mock()
        env.status = "active"
        mock_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=env))
        svc = TestEnvService(mock_db)
        ok = await svc.delete("1")
        assert ok is True
        assert env.status == "inactive"
        assert mock_db.commit.called
