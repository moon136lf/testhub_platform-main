"""
MinIO Storage Client Tests
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.core.storage import StorageClient


class TestStorageClient:
    """测试 MinIO 存储客户端"""

    @patch('app.core.storage.Minio')
    def test_init_creates_bucket(self, mock_minio):
        """测试初始化时自动创建 bucket"""
        mock_client = Mock()
        mock_client.bucket_exists.return_value = False
        mock_minio.return_value = mock_client

        storage = StorageClient()

        mock_client.bucket_exists.assert_called_once()
        mock_client.make_bucket.assert_called_once()

    @patch('app.core.storage.Minio')
    def test_init_skips_existing_bucket(self, mock_minio):
        """测试 bucket 已存在时跳过创建"""
        mock_client = Mock()
        mock_client.bucket_exists.return_value = True
        mock_minio.return_value = mock_client

        storage = StorageClient()

        mock_client.bucket_exists.assert_called_once()
        mock_client.make_bucket.assert_not_called()

    @pytest.mark.asyncio
    @patch('app.core.storage.Minio')
    async def test_upload_bytes_returns_url(self, mock_minio):
        """测试上传字节数据返回 URL"""
        mock_client = Mock()
        mock_client.bucket_exists.return_value = True
        mock_minio.return_value = mock_client

        storage = StorageClient()

        test_bytes = b"test image data"
        object_name = "screenshots/test.png"

        url = await storage.upload_bytes(test_bytes, object_name)

        assert url is not None
        assert isinstance(url, str)
        assert "test.png" in url

    @pytest.mark.asyncio
    @patch('app.core.storage.Minio')
    async def test_upload_file_handles_error(self, mock_minio):
        """测试上传失败时的错误处理"""
        mock_client = Mock()
        mock_client.bucket_exists.return_value = True
        mock_client.put_object.side_effect = Exception("Upload failed")
        mock_minio.return_value = mock_client

        storage = StorageClient()

        with pytest.raises(Exception):
            await storage.upload_bytes(b"test", "test.png")
