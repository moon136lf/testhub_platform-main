"""
Element cache service - 元素库三类 Redis 键 (§8.3) + 自愈置信度衰减 (§8.2.8)

三类 Redis 键：
  1. page_repo:{project_id}:{url_path}      - 页面记录缓存
  2. element:{page_id}:{element_id}          - 元素记录缓存
  3. heal_cache:{element_id}                 - 自愈缓存命中/置信度
"""

import json
import logging
from typing import Optional, Dict, Any
from uuid import UUID

from app.core.redis import redis_client

logger = logging.getLogger(__name__)

# TTL 常量（秒）
PAGE_CACHE_TTL = 3600       # 页面缓存 1 小时
ELEMENT_CACHE_TTL = 3600    # 元素缓存 1 小时
HEAL_CACHE_TTL = 86400      # 自愈缓存 1 天

# 置信度阈值
CONFIDENCE_WRITEBACK_THRESHOLD = 3   # 置信度 >=3 回写仓库
FAILURE_DELETE_THRESHOLD = 3          # 连续失败 3 次删除缓存


def _safe_url_path(url: str) -> str:
    """将 URL 转为 Redis key 安全的 path 段（去协议、替换非法字符）"""
    if not url:
        return "root"
    # 去掉协议头
    cleaned = url.split("://", 1)[-1] if "://" in url else url
    # 替换 Redis key 非法字符 { } 为 _
    return cleaned.replace("{", "_").replace("}", "_")


class ElementCacheService:
    """元素库三类 Redis 键服务"""

    # ---------- 1. 页面缓存 page_repo:{project_id}:{url_path} ----------

    @staticmethod
    def _page_key(project_id, page_url: str) -> str:
        pid = str(project_id) if isinstance(project_id, UUID) else str(project_id)
        return f"page_repo:{pid}:{_safe_url_path(page_url)}"

    @staticmethod
    async def cache_page(project_id, page_url: str, page_data: Dict[str, Any]) -> None:
        """缓存页面记录（入库/抓取后写入）"""
        try:
            key = ElementCacheService._page_key(project_id, page_url)
            await redis_client.set(key, json.dumps(page_data, default=str), ex=PAGE_CACHE_TTL)
            logger.debug(f"Page cached: {key}")
        except Exception as e:
            logger.warning(f"Cache page failed: {e}")

    @staticmethod
    async def get_cached_page(project_id, page_url: str) -> Optional[Dict[str, Any]]:
        """读取缓存的页面记录"""
        try:
            key = ElementCacheService._page_key(project_id, page_url)
            raw = await redis_client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning(f"Get cached page failed: {e}")
            return None

    @staticmethod
    async def invalidate_page(project_id, page_url: str) -> None:
        """使页面缓存失效（页面更新/删除时）"""
        try:
            key = ElementCacheService._page_key(project_id, page_url)
            await redis_client.delete(key)
        except Exception as e:
            logger.warning(f"Invalidate page cache failed: {e}")

    # ---------- 2. 元素缓存 element:{page_id}:{element_id} ----------

    @staticmethod
    def _element_key(page_id, element_id: str) -> str:
        pid = str(page_id) if isinstance(page_id, UUID) else str(page_id)
        return f"element:{pid}:{element_id}"

    @staticmethod
    async def cache_element(page_id, element_id: str, element_data: Dict[str, Any]) -> None:
        """缓存单个元素记录"""
        try:
            key = ElementCacheService._element_key(page_id, element_id)
            await redis_client.set(key, json.dumps(element_data, default=str), ex=ELEMENT_CACHE_TTL)
            logger.debug(f"Element cached: {key}")
        except Exception as e:
            logger.warning(f"Cache element failed: {e}")

    @staticmethod
    async def get_cached_element(page_id, element_id: str) -> Optional[Dict[str, Any]]:
        """读取缓存的元素记录"""
        try:
            key = ElementCacheService._element_key(page_id, element_id)
            raw = await redis_client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning(f"Get cached element failed: {e}")
            return None

    @staticmethod
    async def invalidate_element(page_id, element_id: str) -> None:
        """使元素缓存失效（元素更新/删除时）"""
        try:
            key = ElementCacheService._element_key(page_id, element_id)
            await redis_client.delete(key)
        except Exception as e:
            logger.warning(f"Invalidate element cache failed: {e}")

    @staticmethod
    async def invalidate_page_elements(page_id) -> None:
        """使某页面下所有元素缓存失效（扫描删除）"""
        try:
            pid = str(page_id) if isinstance(page_id, UUID) else str(page_id)
            pattern = f"element:{pid}:*"
            # redis_client.redis 是 aioredis.Redis 实例
            async for key in redis_client.redis.scan_iter(match=pattern, count=100):
                await redis_client.redis.delete(key)
            logger.debug(f"Invalidated all element caches for page {pid}")
        except Exception as e:
            logger.warning(f"Invalidate page elements failed: {e}")

    # ---------- 3. 自愈缓存 heal_cache:{element_id} ----------

    @staticmethod
    def _heal_key(element_id: str) -> str:
        return f"heal_cache:{element_id}"

    @staticmethod
    async def record_heal_success(element_id: str, healed_locator: Dict[str, Any]) -> int:
        """
        记录自愈命中：confidence +1，failure_count 归零

        Returns:
            更新后的 confidence 值
        """
        try:
            key = ElementCacheService._heal_key(element_id)
            raw = await redis_client.get(key)
            data = json.loads(raw) if raw else {
                "confidence": 0, "success_count": 0, "failure_count": 0,
                "healed_locator": None
            }

            data["confidence"] = min(data.get("confidence", 0) + 1, 100)
            data["success_count"] = data.get("success_count", 0) + 1
            data["failure_count"] = 0  # 成功时归零连续失败计数
            data["healed_locator"] = healed_locator

            await redis_client.set(key, json.dumps(data, default=str), ex=HEAL_CACHE_TTL)
            logger.info(f"Heal success recorded for {element_id}: confidence={data['confidence']}")
            return data["confidence"]
        except Exception as e:
            logger.error(f"Record heal success failed: {e}")
            return 0

    @staticmethod
    async def record_heal_failure(element_id: str) -> Dict[str, Any]:
        """
        记录自愈失效：confidence -1，failure_count +1
        连续失败 >= FAILURE_DELETE_THRESHOLD(3) 时删除缓存

        Returns:
            {"deleted": bool, "confidence": int, "failure_count": int}
        """
        try:
            key = ElementCacheService._heal_key(element_id)
            raw = await redis_client.get(key)
            if not raw:
                return {"deleted": False, "confidence": 0, "failure_count": 1}

            data = json.loads(raw)
            data["confidence"] = max(data.get("confidence", 0) - 1, 0)
            data["failure_count"] = data.get("failure_count", 0) + 1

            if data["failure_count"] >= FAILURE_DELETE_THRESHOLD:
                await redis_client.delete(key)
                logger.info(f"Heal cache deleted for {element_id}: {data['failure_count']} consecutive failures")
                return {"deleted": True, "confidence": 0, "failure_count": data["failure_count"]}

            await redis_client.set(key, json.dumps(data, default=str), ex=HEAL_CACHE_TTL)
            logger.info(f"Heal failure recorded for {element_id}: confidence={data['confidence']}, failures={data['failure_count']}")
            return {"deleted": False, "confidence": data["confidence"], "failure_count": data["failure_count"]}
        except Exception as e:
            logger.error(f"Record heal failure failed: {e}")
            return {"deleted": False, "confidence": 0, "failure_count": 0}

    @staticmethod
    async def get_heal_cache(element_id: str) -> Optional[Dict[str, Any]]:
        """读取自愈缓存（confidence、healed_locator 等）"""
        try:
            key = ElementCacheService._heal_key(element_id)
            raw = await redis_client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning(f"Get heal cache failed: {e}")
            return None

    @staticmethod
    async def should_writeback_to_repo(element_id: str) -> bool:
        """判断是否应将自愈定位器回写到元素仓库（confidence >= 3）"""
        data = await ElementCacheService.get_heal_cache(element_id)
        if not data:
            return False
        return data.get("confidence", 0) >= CONFIDENCE_WRITEBACK_THRESHOLD

    @staticmethod
    async def get_writeback_locator(element_id: str) -> Optional[Dict[str, Any]]:
        """获取应回写的自愈定位器（confidence >= 3 时返回）"""
        if await ElementCacheService.should_writeback_to_repo(element_id):
            data = await ElementCacheService.get_heal_cache(element_id)
            return data.get("healed_locator") if data else None
        return None
