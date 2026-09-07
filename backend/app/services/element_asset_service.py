"""元素资产业务服务（阶段1）：引用计数 / 元素CRUD / 调序 / 回收站 / 页面树。

数据源约定：ScriptAsset.step_mapping 每项含 element_name（转脚本时写入），
引用计数 = element_name 精确匹配计数（文本别名匹配由消费端 find_by_name 处理）。
性能路标：数据量大时可改用 PG JSONB path 查询（jsonb_path_exists），当前量级无需。"""
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Dict, List
from uuid import UUID

from sqlalchemy import select

from app.models.test_case import ScriptAsset

logger = logging.getLogger(__name__)

# 可编辑字段白名单（防乱写）
_EDITABLE_FIELDS = {"element_name", "element_type", "element_text"}


def _to_uuid(value: str):
    """project/id 字符串转 UUID；非法输入返回 None（调用方决定回退策略）。"""
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


class ElementAssetService:
    def __init__(self, db):
        self.db = db

    async def _load_scripts(self, project_id: str) -> List[ScriptAsset]:
        pid = _to_uuid(project_id) or project_id
        result = await self.db.execute(
            select(ScriptAsset).where(ScriptAsset.project_id == pid)
        )
        return result.scalars().all()

    async def count_references(self, project_id: str, element_name: str) -> int:
        """统计引用了该元素别名的脚本数（同脚本多步骤引用只计 1 次）。"""
        if not element_name:
            return 0
        n = 0
        for s in await self._load_scripts(project_id):
            for m in (s.step_mapping or []):
                if isinstance(m, dict) and m.get("element_name") == element_name:
                    n += 1
                    break
        return n

    async def list_referring_scripts(self, project_id: str, element_name: str) -> List[Dict]:
        """引用该元素的脚本清单（详情抽屉用）。"""
        if not element_name:
            return []
        refs = []
        for s in await self._load_scripts(project_id):
            for m in (s.step_mapping or []):
                if isinstance(m, dict) and m.get("element_name") == element_name:
                    refs.append({"id": str(s.id), "name": s.name})
                    break
        return refs

    async def update_element(self, element_id: str, fields: Dict) -> "ElementRepository":
        """编辑元素（白名单字段）。未知字段抛 ValueError。"""
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        for k, v in fields.items():
            if k not in _EDITABLE_FIELDS:
                raise ValueError(f"字段不可编辑: {k}")
            setattr(el, k, v)
        await self.db.commit()
        return el

    async def reorder_locator(self, element_id: str, index: int, direction: str) -> None:
        """调序：上移/下移相邻交换，score 跟随位置重排（150-pos*10）——排序即置信度。"""
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        sts = (el.locator_strategies or {}).get("strategies", [])
        if index < 0 or index >= len(sts):
            return  # 越界（含空列表），静默
        j = index - 1 if direction == "up" else index + 1
        if j < 0 or j >= len(sts):
            return  # 已到边界，静默
        sts[index], sts[j] = sts[j], sts[index]
        for pos, s in enumerate(sts):
            s["score"] = max(0, 150 - pos * 10)
        el.locator_strategies = {"strategies": sts}
        await self.db.commit()

    async def add_locator(self, element_id: str, ltype: str, value: str, score: int = 50) -> None:
        """新增自定义定位器（手工来源）。"""
        if not value or not value.strip():
            raise ValueError("定位值不能为空")
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        sts = (el.locator_strategies or {}).get("strategies", [])
        sts.append({
            "type": ltype, "value": value.strip(), "score": score,
            "unique": False, "verified": False, "source": "manual",
        })
        el.locator_strategies = {"strategies": sts}
        await self.db.commit()

    async def recycle_element(self, element_id: str) -> None:
        """软删进回收站（30天可恢复；调用方须先做引用计数确认）。"""
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        el.status = "deleted"
        el.recycled_at = datetime.now(timezone.utc)
        await self.db.commit()

    async def restore_element(self, element_id: str) -> None:
        """从回收站恢复。"""
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        el.status = "active"
        el.recycled_at = None
        await self.db.commit()

    async def list_recycled(self, project_id: str) -> List:
        """回收站列表（30天内；清理任务后置）。"""
        from app.models.element import ElementRepository
        uid = _to_uuid(project_id) or project_id
        result = await self.db.execute(
            select(ElementRepository).where(
                ElementRepository.project_id == uid,
                ElementRepository.status == "deleted",
            )
        )
        return result.scalars().all()
