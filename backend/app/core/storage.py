"""
MinIO Storage Client
"""

from minio import Minio
from minio.error import S3Error
from app.core.config import settings
import logging
import io
from typing import Optional

logger = logging.getLogger(__name__)


class StorageClient:
    """MinIO 对象存储客户端"""

    _instance: Optional["StorageClient"] = None

    def __init__(self):
        # Parse endpoint (remove http:// prefix for Minio client)
        endpoint = settings.STORAGE_ENDPOINT.replace("http://", "").replace("https://", "")

        try:
            self.client = Minio(
                endpoint,
                access_key=settings.STORAGE_ACCESS_KEY,
                secret_key=settings.STORAGE_SECRET_KEY,
                secure=False  # Use HTTP for local development
            )
            self.bucket_name = settings.STORAGE_BUCKET
            self._ensure_bucket()
            logger.info(f"MinIO client initialized: {endpoint}/{self.bucket_name}")
        except Exception as e:
            # MinIO 不可用时降级为内存存储（测试/开发环境），避免模块导入即崩溃
            logger.warning(f"MinIO unavailable, using in-memory fallback: {e}")
            self.client = None
            self.bucket_name = settings.STORAGE_BUCKET
            self._fallback_store = {}

    def _ensure_bucket(self):
        """确保 bucket 存在，不存在则创建"""
        if self.client is None:
            return
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Created bucket: {self.bucket_name}")
            else:
                logger.info(f"Bucket already exists: {self.bucket_name}")
        except S3Error as e:
            logger.error(f"Failed to ensure bucket: {e}")
            raise

    async def upload_bytes(self, data: bytes, object_name: str) -> str:
        """
        上传字节数据到 MinIO

        Args:
            data: 字节数据
            object_name: 对象名称（相对路径）

        Returns:
            可访问的 URL
        """
        try:
            if self.client is None:
                # 降级：内存存储，返回占位 URL
                self._fallback_store[object_name] = data
                return f"{settings.STORAGE_ENDPOINT}/{self.bucket_name}/{object_name}"

            # 转换为 BytesIO 对象
            data_stream = io.BytesIO(data)
            data_length = len(data)

            # 上传到 MinIO
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=data_stream,
                length=data_length
            )

            # 构造访问 URL
            url = f"{settings.STORAGE_ENDPOINT}/{self.bucket_name}/{object_name}"
            logger.info(f"Uploaded file: {url}")
            return url

        except S3Error as e:
            logger.error(f"Failed to upload file {object_name}: {e}")
            raise Exception(f"Storage upload failed: {str(e)}")

    async def upload_file(self, file_path: str, object_name: Optional[str] = None) -> str:
        """
        上传本地文件到 MinIO

        Args:
            file_path: 本地文件路径
            object_name: 对象名称（如不提供则使用文件名）

        Returns:
            可访问的 URL
        """
        import os

        if object_name is None:
            object_name = os.path.basename(file_path)

        try:
            self.client.fput_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                file_path=file_path
            )

            url = f"{settings.STORAGE_ENDPOINT}/{self.bucket_name}/{object_name}"
            logger.info(f"Uploaded file: {url}")
            return url

        except S3Error as e:
            logger.error(f"Failed to upload file {file_path}: {e}")
            raise Exception(f"Storage upload failed: {str(e)}")

    def delete_object(self, object_name: str):
        """删除对象"""
        try:
            self.client.remove_object(self.bucket_name, object_name)
            logger.info(f"Deleted object: {object_name}")
        except S3Error as e:
            logger.error(f"Failed to delete object {object_name}: {e}")
            raise

    def object_exists(self, object_name: str) -> bool:
        """检查对象是否存在"""
        try:
            self.client.stat_object(self.bucket_name, object_name)
            return True
        except S3Error:
            return False


# 全局实例
storage_client = StorageClient()
