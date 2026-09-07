"""元素资产业务服务（阶段1）：引用计数 / 元素CRUD / 调序 / 回收站 / 页面树。

数据源约定：ScriptAsset.step_mapping 每项含 element_name（转脚本时写入），
引用计数 = element_name 精确匹配计数（文本别名匹配由消费端 find_by_name 处理）。"""
import logging
from typing import Dict, List
from uuid import UUID

from sqlalchemy import select

from app.models.test_case import ScriptAsset

logger = logging.getLogger(__name__)


class ElementAssetService:
    def __init__(self, db):
        self.db = db

    async def _load_scripts(self, project_id: str) -> List[ScriptAsset]:
        try:
            pid = UUID(str(project_id))
        except (ValueError, TypeError):
            pid = project_id
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
        refs = []
        for s in await self._load_scripts(project_id):
            for m in (s.step_mapping or []):
                if isinstance(m, dict) and m.get("element_name") == element_name:
                    refs.append({"id": str(s.id), "name": s.name})
                    break
        return refs
