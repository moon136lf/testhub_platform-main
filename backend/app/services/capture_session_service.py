"""
Capture session service - P3 会话式抓取工作台

抓取结果暂存于 Redis（而非前端往返），支持:
  - 同一会话多次抓取，结果按批次累积
  - 逐元素 勾选/取消/删除（服务端持久状态）
  - 全选/全不选
  - 最终按勾选一次性入库

Redis 结构:
  capture_session:{session_id}  -> JSON {project_id, created_at, batches: [...], elements: {...}}
  elements 按 temp_id 索引: {temp_id: {element_data..., included: bool, batch_idx: int}}
  batches: [{url, screenshot_url, fetched_at, temp_ids: [...]}]

TTL: 2 小时（工作台单次使用时长上限，过期即弃）
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.redis import redis_client

logger = logging.getLogger(__name__)

SESSION_TTL = 7200  # 2 小时
MAX_BATCHES = 20    # 单会话批次上限（防滥用）


class CaptureSessionService:
    """会话式抓取暂存（Redis）"""

    @staticmethod
    def _key(session_id: str) -> str:
        return f"capture_session:{session_id}"

    @staticmethod
    async def create(project_id: str) -> Dict[str, Any]:
        """创建空会话，返回 {session_id, project_id, batches: [], elements: {}}"""
        session_id = f"cap_{uuid.uuid4().hex[:12]}"
        state = {
            "project_id": str(project_id),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "batches": [],
            "elements": {},
        }
        await redis_client.set(
            CaptureSessionService._key(session_id),
            json.dumps(state, ensure_ascii=False),
            ex=SESSION_TTL,
        )
        return {"session_id": session_id, **state}

    @staticmethod
    async def _load(session_id: str) -> Optional[Dict[str, Any]]:
        raw = await redis_client.get(CaptureSessionService._key(session_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.error(f"Capture session {session_id} corrupted JSON")
            return None

    @staticmethod
    async def _save(session_id: str, state: Dict[str, Any]) -> None:
        # 每次写操作刷新 TTL（工作台活跃期不中断）
        await redis_client.set(
            CaptureSessionService._key(session_id),
            json.dumps(state, ensure_ascii=False, default=str),
            ex=SESSION_TTL,
        )

    @staticmethod
    async def get(session_id: str) -> Optional[Dict[str, Any]]:
        return await CaptureSessionService._load(session_id)

    @staticmethod
    async def delete(session_id: str) -> bool:
        state = await CaptureSessionService._load(session_id)
        if state is None:
            return False
        await redis_client.delete(CaptureSessionService._key(session_id))
        return True

    @staticmethod
    async def add_batch(
        session_id: str,
        url: str,
        screenshot_url: str,
        elements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """追加一个抓取批次（新元素 included=True 默认勾选；同 temp_id 不可能出现，uuid 兜底）"""
        state = await CaptureSessionService._load(session_id)
        if state is None:
            raise KeyError(f"Capture session not found or expired: {session_id}")
        if len(state["batches"]) >= MAX_BATCHES:
            raise ValueError(f"Batch limit ({MAX_BATCHES}) reached for this session")

        batch_idx = len(state["batches"])
        temp_ids = []
        for elem in elements:
            tid = elem.get("temp_id") or f"elem_{batch_idx}_{uuid.uuid4().hex[:8]}"
            elem = dict(elem)
            elem["temp_id"] = tid
            elem["included"] = True
            elem["batch_idx"] = batch_idx
            state["elements"][tid] = elem
            temp_ids.append(tid)

        state["batches"].append({
            "url": url,
            "screenshot_url": screenshot_url,
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "temp_ids": temp_ids,
        })
        await CaptureSessionService._save(session_id, state)
        return {
            "batch_idx": batch_idx,
            "batch_count": len(state["batches"]),
            "added": len(temp_ids),
            "total_elements": len(state["elements"]),
        }

    @staticmethod
    async def set_element_included(session_id: str, temp_id: str, included: bool) -> bool:
        state = await CaptureSessionService._load(session_id)
        if state is None or temp_id not in state["elements"]:
            return False
        state["elements"][temp_id]["included"] = bool(included)
        await CaptureSessionService._save(session_id, state)
        return True

    @staticmethod
    async def set_all_included(session_id: str, included: bool) -> int:
        state = await CaptureSessionService._load(session_id)
        if state is None:
            return 0
        count = 0
        for elem in state["elements"].values():
            elem["included"] = bool(included)
            count += 1
        await CaptureSessionService._save(session_id, state)
        return count

    @staticmethod
    async def delete_element(session_id: str, temp_id: str) -> bool:
        """从会话中移除元素（同时从批次 temp_ids 里摘除）"""
        state = await CaptureSessionService._load(session_id)
        if state is None or temp_id not in state["elements"]:
            return False
        elem = state["elements"].pop(temp_id)
        batch_idx = elem.get("batch_idx")
        if batch_idx is not None and batch_idx < len(state["batches"]):
            batch = state["batches"][batch_idx]
            batch["temp_ids"] = [t for t in batch["temp_ids"] if t != temp_id]
        await CaptureSessionService._save(session_id, state)
        return True

    @staticmethod
    async def get_selected_elements(session_id: str) -> Optional[Dict[str, Any]]:
        """取所有 included=True 的元素（入库用），返回 {project_id, elements: [...], batches}"""
        state = await CaptureSessionService._load(session_id)
        if state is None:
            return None
        selected = [e for e in state["elements"].values() if e.get("included")]
        return {
            "project_id": state["project_id"],
            "elements": selected,
            "total_in_session": len(state["elements"]),
            "total_selected": len(selected),
        }

    @staticmethod
    async def remove_batch(session_id: str, batch_idx: int) -> int:
        """移除整个批次（其元素一并清除），返回删除的元素数"""
        state = await CaptureSessionService._load(session_id)
        if state is None or batch_idx >= len(state["batches"]):
            return 0
        batch = state["batches"][batch_idx]
        removed = 0
        for tid in batch.get("temp_ids", []):
            if state["elements"].pop(tid, None) is not None:
                removed += 1
        # 批次标记为空（保留索引对齐，避免重排 batch_idx）
        state["batches"][batch_idx]["temp_ids"] = []
        state["batches"][batch_idx]["removed"] = True
        await CaptureSessionService._save(session_id, state)
        return removed
