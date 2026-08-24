"""
Server-Sent Events (SSE) Stream Handler
"""

import asyncio
import json
from datetime import datetime
from typing import AsyncGenerator, Optional
import logging

from app.core.redis import redis_client

logger = logging.getLogger(__name__)


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
        tokens_estimated_total: int = 0
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

        try:
            # 推送到 Redis List
            await redis_client.redis.lpush(self.redis_key, json.dumps(message))
            # 设置过期时间
            await redis_client.redis.expire(self.redis_key, self.ttl)
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
            last_id = 0
            timeout_count = 0
            max_timeout = 60  # 最多等待 60 次（约 5 分钟）

            while timeout_count < max_timeout:
                # 从 Redis List 中获取消息
                messages = await redis_client.redis.lrange(self.redis_key, 0, -1)

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
            await redis_client.redis.delete(self.redis_key)
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
            result_json = await redis_client.redis.get(result_key)

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
            await redis_client.redis.setex(
                result_key,
                self.ttl,
                json.dumps(result)
            )
            logger.info(f"Cached task result: {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to cache result: {e}")
