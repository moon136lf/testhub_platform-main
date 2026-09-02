"""
SSE (Server-Sent Events) endpoints
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.core.sse import SSEStream
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/parse-result/{session_id}")
async def get_parse_result(session_id: str):
    """
    获取文档解析任务缓存结果（parse_document_task 完成后写入 task_result:{session_id}）

    前端 Step 2「解析并继续」轮询此端点，拿到解析文本后再进入 Step 3。
    """
    sse = SSEStream(session_id)
    result = await sse.get_cached_result()
    if result is None:
        return {"code": 1, "message": "not ready", "data": None}
    return {"code": 0, "message": "ok", "data": result}


@router.get("/stream/{session_id}")
async def stream_events(session_id: str):
    """
    SSE 流端点

    客户端通过此端点建立 EventSource 连接，实时接收任务进度消息。

    Args:
        session_id: 会话 ID（从 /fetch 端点获取）

    Returns:
        SSE 流响应
    """
    logger.info(f"SSE connection established: {session_id}")

    sse = SSEStream(session_id)

    async def event_generator():
        """生成 SSE 事件流"""
        try:
            async for message in sse.stream_messages():
                yield f"data: {message}\n\n"
        except Exception as e:
            logger.error(f"SSE stream error for {session_id}: {e}")
            yield f"event: error\ndata: {str(e)}\n\n"
        finally:
            logger.info(f"SSE connection closed: {session_id}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
            "Access-Control-Allow-Origin": "*"
        }
    )


@router.delete("/stream/{session_id}")
async def clear_stream(session_id: str):
    """
    清除会话消息

    用于手动清理 Redis 中的 SSE 消息
    """
    sse = SSEStream(session_id)
    await sse.clear_messages()

    return {
        "code": 0,
        "message": "Stream messages cleared"
    }
