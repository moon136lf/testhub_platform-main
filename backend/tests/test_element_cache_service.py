"""
测试 ElementCacheService 三类 Redis 键 + 自愈置信度衰减逻辑
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.element_cache_service import (
    ElementCacheService,
    CONFIDENCE_WRITEBACK_THRESHOLD,
    FAILURE_DELETE_THRESHOLD,
    _safe_url_path,
)


@pytest.fixture
def mock_redis():
    """Mock redis_client"""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.scan_iter = MagicMock(return_value=iter([]))
    return redis


class TestSafeUrlPath:
    def test_removes_protocol(self):
        assert _safe_url_path("https://example.com/login") == "example.com/login"

    def test_replaces_braces(self):
        assert _safe_url_path("http://test/{page}") == "test/_page_"

    def test_empty_url(self):
        assert _safe_url_path("") == "root"


class TestPageCache:
    @pytest.mark.asyncio
    async def test_cache_page_writes_correct_key(self, mock_redis):
        project_id = uuid4()
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            await ElementCacheService.cache_page(project_id, "https://example.com/login", {"id": "p1"})

        # 验证 key 格式 page_repo:{project_id}:{url_path}
        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        assert key.startswith("page_repo:")
        assert str(project_id) in key
        assert "example.com/login" in key

    @pytest.mark.asyncio
    async def test_get_cached_page_returns_dict(self, mock_redis):
        mock_redis.get.return_value = json.dumps({"id": "p1", "page_name": "Login"})
        project_id = uuid4()
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            result = await ElementCacheService.get_cached_page(project_id, "https://example.com/login")

        assert result == {"id": "p1", "page_name": "Login"}

    @pytest.mark.asyncio
    async def test_get_cached_page_returns_none_when_missing(self, mock_redis):
        mock_redis.get.return_value = None
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            result = await ElementCacheService.get_cached_page(uuid4(), "https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_page_deletes_key(self, mock_redis):
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            await ElementCacheService.invalidate_page(uuid4(), "https://example.com/login")

        mock_redis.delete.assert_called_once()


class TestElementCache:
    @pytest.mark.asyncio
    async def test_cache_element_writes_correct_key(self, mock_redis):
        page_id = uuid4()
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            await ElementCacheService.cache_element(page_id, "btn-login", {"element_id": "btn-login"})

        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        assert key.startswith("element:")
        assert str(page_id) in key
        assert "btn-login" in key

    @pytest.mark.asyncio
    async def test_get_cached_element_returns_dict(self, mock_redis):
        mock_redis.get.return_value = json.dumps({"element_id": "btn", "type": "button"})
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            result = await ElementCacheService.get_cached_element(uuid4(), "btn")

        assert result["element_id"] == "btn"


class TestHealCacheSuccessFailure:
    @pytest.mark.asyncio
    async def test_record_heal_success_increments_confidence(self, mock_redis):
        mock_redis.get.return_value = json.dumps({
            "confidence": 2, "success_count": 2, "failure_count": 1, "healed_locator": None
        })
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            confidence = await ElementCacheService.record_heal_success("elem-1", {"type": "text", "value": "登录"})

        assert confidence == 3
        # 验证 success_count +1, failure_count 归零
        saved = json.loads(mock_redis.set.call_args[0][1])
        assert saved["success_count"] == 3
        assert saved["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_record_heal_success_initializes_when_no_cache(self, mock_redis):
        mock_redis.get.return_value = None
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            confidence = await ElementCacheService.record_heal_success("elem-1", {"type": "id", "value": "#x"})

        assert confidence == 1

    @pytest.mark.asyncio
    async def test_record_heal_failure_decrements_confidence(self, mock_redis):
        mock_redis.get.return_value = json.dumps({
            "confidence": 5, "success_count": 5, "failure_count": 0, "healed_locator": {}
        })
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            result = await ElementCacheService.record_heal_failure("elem-1")

        assert result["deleted"] is False
        assert result["confidence"] == 4
        assert result["failure_count"] == 1

    @pytest.mark.asyncio
    async def test_record_heal_failure_deletes_after_threshold(self, mock_redis):
        # failure_count 已达阈值-1，再失败一次应触发删除
        mock_redis.get.return_value = json.dumps({
            "confidence": 1, "success_count": 1, "failure_count": FAILURE_DELETE_THRESHOLD - 1, "healed_locator": {}
        })
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            result = await ElementCacheService.record_heal_failure("elem-1")

        assert result["deleted"] is True
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_writeback_to_repo_true_when_confidence_high(self, mock_redis):
        mock_redis.get.return_value = json.dumps({
            "confidence": CONFIDENCE_WRITEBACK_THRESHOLD, "healed_locator": {"type": "id", "value": "#x"}
        })
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            should = await ElementCacheService.should_writeback_to_repo("elem-1")
            locator = await ElementCacheService.get_writeback_locator("elem-1")

        assert should is True
        assert locator == {"type": "id", "value": "#x"}

    @pytest.mark.asyncio
    async def test_should_writeback_to_repo_false_when_low_confidence(self, mock_redis):
        mock_redis.get.return_value = json.dumps({"confidence": 1, "healed_locator": {}})
        with patch('app.services.element_cache_service.redis_client', mock_redis):
            should = await ElementCacheService.should_writeback_to_repo("elem-1")

        assert should is False
