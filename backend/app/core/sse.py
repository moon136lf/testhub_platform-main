"""
Server-Sent Events (SSE) Stream Handler

跨循环安全设计（重要）：
redis.asyncio 连接池的连接绑定创建它的循环。本项目同一进程内有多个事件循环：
  - FastAPI 宿主 loop（Windows --reload 下是 Selector）
  - pw-bridge 专用 Proactor loop（会话抓取 on_progress 回调在此执行）
  - Celery worker 每任务 asyncio.run 的新循环
共享一个全局 client 会报 'got Future attached to a different loop'。
因此 SSE 模块用 _loop_local_client() 按「当前运行的循环」取用独立 client
（每个循环一个连接池，互不污染；不再复用全局 redis_client）。
"""

import asyncio
import json
import logging
import weakref
from datetime import datetime
from typing import AsyncGenerator, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# 每个（存活的）事件循环一个独立 redis client；loop 结束后条目自动清理
_clients_by_loop: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


async def _loop_local_client():
    """取当前运行循环专属的 redis client（无则创建）。"""
    loop = asyncio.get_running_loop()
    client = _clients_by_loop.get(loop)
    if client is None or getattr(client, "connection_pool", None) is None:
        client = _make_client()
        _clients_by_loop[loop] = client
    return client


def _make_client():
    import redis.asyncio as aioredis
    return aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )


async def get_loop_client():
    """取当前运行循环专属的 redis client（无则创建）。外部需要直连时用。"""
    return await _loop_local_client()


class SSEStream:
    """SSE 流处理器"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.redis_key = f"sse:{session_id}"
        self.ttl = 1800  # 30 minutes

    async def send_message(
        self,
        type: str,
        stage: str,
        content: str,
        progress: float = 0,
        tokens_used: int = 0,
        tokens_estimated_total: int = 0,
        data: Optional[dict] = None
    ):
        """
        发送 SSE 消息到 Redis

        Args:
            type: 消息类型 (system/ai/user/error/cost)
            stage: 阶段 (parse_doc/identify_point/fetch/etc)
            content: 消息内容
            progress: 进度 (0.0-1.0)
            tokens_used: 已消耗 Token 数
            tokens_estimated_total: 预估总 Token 数
            data: 附加载荷 (如抓取完成的 elements/screenshot_url)
        """
        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "type": type,
            "stage": stage,
            "content": content,
            "progress": progress,
            "tokens_used": tokens_used,
            "tokens_estimated_total": tokens_estimated_total
        }
        if data is not None:
            message["data"] = data

        try:
            client = await _loop_local_client()
            # 推送到 Redis List（当前循环专属 client，见模块 docstring）
            await client.lpush(self.redis_key, json.dumps(message))
            # 设置过期时间
            await client.expire(self.redis_key, self.ttl)
            logger.debug(f"SSE message sent: {self.session_id} - {content}")
        except Exception as e:
            logger.error(f"Failed to send SSE message: {e}")

    async def stream_messages(self) -> AsyncGenerator[str, None]:
        """
        从 Redis 读取并流式返回 SSE 消息

        Yields:
            JSON 格式的消息字符串
        """
        try:
            last_id = -1  # -1：index 0 的首条消息也要产出（0 会吞掉第一条）
            timeout_count = 0
            max_timeout = 60  # 最多等待 60 次（约 5 分钟）

            while timeout_count < max_timeout:
                # 从 Redis List 中获取消息（当前循环专属 client，见模块 docstring）
                client = await _loop_local_client()
                messages = await client.lrange(self.redis_key, 0, -1)

                if messages:
                    # 反转列表（Redis lpush 是倒序的）
                    messages.reverse()

                    # 只返回新消息
                    for i, msg in enumerate(messages):
                        if i > last_id:
                            yield msg
                            last_id = i

                    # 检查进度是否完成
                    try:
                        last_msg = json.loads(messages[-1])
                        if last_msg.get("progress", 0) >= 1.0:
                            logger.info(f"SSE stream completed: {self.session_id}")
                            break
                    except (json.JSONDecodeError, IndexError):
                        pass

                    timeout_count = 0  # 重置超时计数
                else:
                    timeout_count += 1

                # 等待新消息
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            error_message = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "type": "error",
                "stage": "stream",
                "content": f"Stream error: {str(e)}",
                "progress": 0
            }
            yield json.dumps(error_message)

    async def clear_messages(self):
        """清除会话消息"""
        try:
            client = await _loop_local_client()
            await client.delete(self.redis_key)
            logger.info(f"Cleared SSE messages: {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to clear SSE messages: {e}")

    async def get_cached_result(self) -> Optional[dict]:
        """
        获取任务缓存结果

        Returns:
            任务结果字典，如果不存在返回 None
        """
        try:
            result_key = f"task_result:{self.session_id}"
            client = await _loop_local_client()
            result_json = await client.get(result_key)

            if result_json:
                return json.loads(result_json)
            return None
        except Exception as e:
            logger.error(f"Failed to get cached result: {e}")
            return None

    async def cache_result(self, result: dict):
        """
        缓存任务结果

        Args:
            result: 任务结果字典
        """
        try:
            result_key = f"task_result:{self.session_id}"
            client = await _loop_local_client()
            await client.setex(
                result_key,
                self.ttl,
                json.dumps(result)
            )
            logger.info(f"Cached task result: {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to cache result: {e}")
