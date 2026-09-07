"""元素资产业务服务（阶段1）：引用计数 / 元素CRUD / 调序 / 回收站 / 页面树。

数据源约定：ScriptAsset.step_mapping 每项含 element_name（转脚本时写入），
引用计数 = element_name 精确匹配计数（文本别名匹配由消费端 find_by_name 处理）。
性能路标：数据量大时可改用 PG JSONB path 查询（jsonb_path_exists），当前量级无需。"""
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
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

    # ---------------- 页面树（层级 + 编辑 + 上下移 + 守护删除） ----------------

    async def create_sub_page(self, project_id: str, parent_id: Optional[str],
                              page_name: str, page_url: str = "") -> "PageRepository":
        """创建子页面（parent_id=None 即根级）。"""
        if not page_name or not page_name.strip():
            raise ValueError("页面名称不能为空")
        from app.models.element import PageRepository
        page = PageRepository(
            project_id=_to_uuid(project_id) or project_id,
            parent_id=_uuid.UUID(parent_id) if parent_id else None,
            page_name=page_name.strip()[:100],
            page_url=page_url or f"/__placeholder__/{page_name.strip()}",
        )
        self.db.add(page)
        await self.db.commit()
        return page

    async def rename_page(self, page_id: str, page_name: str) -> None:
        """重命名页面。"""
        if not page_name or not page_name.strip():
            raise ValueError("页面名称不能为空")
        from app.models.element import PageRepository
        page = await self.db.get(PageRepository, _uuid.UUID(page_id))
        if not page:
            raise ValueError("页面不存在")
        page.page_name = page_name.strip()[:100]
        await self.db.commit()

    async def move_page(self, page_id: str, direction: str) -> None:
        """同级上移/下移：与相邻页面交换 sort_order。"""
        from app.models.element import PageRepository
        page = await self.db.get(PageRepository, _uuid.UUID(page_id))
        if not page:
            raise ValueError("页面不存在")
        result = await self.db.execute(
            select(PageRepository).where(
                PageRepository.project_id == page.project_id,
                PageRepository.parent_id == page.parent_id,
            ).order_by(PageRepository.sort_order, PageRepository.created_at)
        )
        siblings = list(result.scalars().all())
        idx = next((i for i, p in enumerate(siblings) if p.id == page.id), None)
        if idx is None:
            return
        j = idx - 1 if direction == "up" else idx + 1
        if j < 0 or j >= len(siblings):
            return  # 已到边界，静默
        siblings[idx].sort_order, siblings[j].sort_order = siblings[j].sort_order, siblings[idx].sort_order
        await self.db.commit()

    async def delete_page(self, page_id: str, move_to_page_id: Optional[str] = None,
                          force: bool = False) -> None:
        """删页面：有子页面拒绝；有元素时须给迁移目标或 force（元素一起进回收站）。

        move_to_page_id: 页面下元素迁移到此页面
        force: 页面下元素直接进回收站（status=deleted + recycled_at）"""
        from app.models.element import PageRepository, ElementRepository
        page = await self.db.get(PageRepository, _uuid.UUID(page_id))
        if not page:
            raise ValueError("页面不存在")
        children = await self.db.execute(
            select(PageRepository).where(PageRepository.parent_id == page.id)
        )
        if children.scalars().all():
            raise ValueError("存在子页面，请先删除/迁移子页面")
        n = await self._count_page_elements(str(page.id))
        if n > 0 and not force and not move_to_page_id:
            raise ValueError(f"页面下有 {n} 个元素，请指定迁移目标页面或选择一并删除")
        if n > 0 and move_to_page_id:
            target = _uuid.UUID(move_to_page_id)
            from sqlalchemy import func as _func
            t = await self.db.execute(
                select(_func.count(PageRepository.id)).where(PageRepository.id == target)
            )
            if not (t.scalar() or 0):
                raise ValueError("迁移目标页面不存在")
            await self.db.execute(
                ElementRepository.__table__.update()
                .where(ElementRepository.page_id == page.id)
                .values(page_id=target)
            )
        elif n > 0 and force:
            await self.db.execute(
                ElementRepository.__table__.update()
                .where(ElementRepository.page_id == page.id)
                .values(status="deleted", recycled_at=datetime.now(timezone.utc))
            )
        await self.db.delete(page)
        await self.db.commit()

    async def _count_page_elements(self, page_id: str) -> int:
        from app.models.element import ElementRepository
        from sqlalchemy import func
        uid = _to_uuid(page_id)
        if uid is None:
            return 0
        r = await self.db.execute(
            select(func.count(ElementRepository.id)).where(
                ElementRepository.page_id == uid,
                ElementRepository.status == "active",
            )
        )
        return r.scalar() or 0
