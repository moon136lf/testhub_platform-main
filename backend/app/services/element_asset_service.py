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

    # ---------------- 全局共享元素 + 元素列表 + 手工创建 ----------------

    async def create_element(self, project_id: str, name: str, etype: str, text: str,
                             scope: str = "page", page_id: Optional[str] = None,
                             locators: Optional[List[Dict]] = None) -> "ElementRepository":
        """新建元素（手工）。scope=global 不挂页面；page 级必须挂页面。"""
        from app.models.element import ElementRepository
        scope = scope or "page"
        if scope == "global" and page_id:
            raise ValueError("全局元素不挂页面")
        if scope == "page" and not page_id:
            raise ValueError("页面级元素必须指定页面")
        el = ElementRepository(
            project_id=_to_uuid(project_id) or project_id,
            page_id=_uuid.UUID(page_id) if page_id else None,
            scope=scope,
            element_id=f"manual-{_uuid.uuid4().hex[:12]}",
            element_name=name[:100] if name else "未命名元素",
            element_type=etype or "other",
            element_text=(text or "")[:200] or None,
            locator_strategies={"strategies": locators or []},
            source="manual",
            status="active",
        )
        self.db.add(el)
        await self.db.commit()
        return el

    async def list_elements(self, project_id: str, scope: Optional[str] = None,
                            page_id: Optional[str] = None, status: str = "active",
                            keyword: Optional[str] = None) -> List:
        """元素列表：scope/page/keyword 过滤，updated_at 倒序（NULL 最后）。

        page_id='all' 表示全部（含全局）；page_id=具体页面时自动附带全局元素
        （全局可被任何页面的脚本引用）。"""
        from app.models.element import ElementRepository
        from sqlalchemy import or_
        conds = [ElementRepository.project_id == (_to_uuid(project_id) or project_id),
                 ElementRepository.status == status]
        if scope:
            conds.append(ElementRepository.scope == scope)
        if page_id and page_id != "all":
            uid = _to_uuid(page_id)
            if uid is None:
                raise ValueError("无效的页面ID")
            conds.append(or_(ElementRepository.page_id == uid,
                             ElementRepository.scope == "global"))
        if keyword:
            conds.append(or_(ElementRepository.element_name.ilike(f"%{keyword}%"),
                             ElementRepository.element_text.ilike(f"%{keyword}%")))
        result = await self.db.execute(
            select(ElementRepository).where(*conds)
            .order_by(ElementRepository.updated_at.desc().nulls_last())
        )
        return result.scalars().all()

    async def list_elements_paged(self, project_id: str, scope: Optional[str] = None,
                                  page_id: Optional[str] = None, keyword: Optional[str] = None,
                                  page: int = 1, page_size: int = 10):
        """分页版元素列表：返回 (rows, total)，updated_at 倒序（NULL 最后）。

        与 list_elements 同过滤条件；page_size 上限 100 由端点 Query 约束。"""
        from app.models.element import ElementRepository
        from sqlalchemy import func as _func, or_
        conds = [ElementRepository.project_id == (_to_uuid(project_id) or project_id),
                 ElementRepository.status == "active"]
        if scope:
            conds.append(ElementRepository.scope == scope)
        if page_id and page_id != "all":
            uid = _to_uuid(page_id)
            if uid is None:
                raise ValueError("无效的页面ID")
            conds.append(or_(ElementRepository.page_id == uid,
                             ElementRepository.scope == "global"))
        if keyword:
            conds.append(or_(ElementRepository.element_name.ilike(f"%{keyword}%"),
                             ElementRepository.element_text.ilike(f"%{keyword}%")))
        cresult = await self.db.execute(
            select(_func.count(ElementRepository.id)).where(*conds)
        )
        total = cresult.scalar() or 0
        result = await self.db.execute(
            select(ElementRepository).where(*conds)
            .order_by(ElementRepository.updated_at.desc().nulls_last())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return result.scalars().all(), total

    async def attach_page_names(self, els: List) -> List[Dict]:
        """批量给元素 dict 附 page_name（全局元素无页面 → None）。"""
        from app.models.element import PageRepository
        page_ids = {e.page_id for e in els if getattr(e, "page_id", None)}
        page_names: Dict = {}
        if page_ids:
            result = await self.db.execute(
                select(PageRepository).where(PageRepository.id.in_(page_ids))
            )
            page_names = {p.id: (p.page_name or "") for p in result.scalars().all()}
        out = []
        for e in els:
            d = e.to_dict()
            d["page_name"] = page_names.get(e.page_id)
            out.append(d)
        return out

    async def set_status(self, element_id: str, status: str) -> "ElementRepository":
        """启用/禁用开关：active=启用，deprecated=禁用（回收站状态 deleted 不可用此端点改）。

        禁用后转脚本链路 find_by_name（status=='active' 过滤）自动不再匹配。"""
        if status not in ("active", "deprecated"):
            raise ValueError("status 仅支持 active/deprecated")
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el or el.status == "deleted":
            raise ValueError("元素不存在")
        el.status = status
        await self.db.commit()
        return el

    # ---------------- 导入导出（可移植 JSON，跨项目/环境复用） ----------------

    async def export_elements(self, project_id: str) -> Dict:
        """导出项目全部 active 元素为可移植 JSON（跨项目/环境复用）。

        每个元素附带 page_name（跨项目导入时按名称匹配页面，page_id 不可跨项目复用）。"""
        from app.models.element import ElementRepository, PageRepository
        pid = _to_uuid(project_id) or project_id
        pages = await self.db.execute(
            select(PageRepository).where(PageRepository.project_id == pid)
        )
        page_names = {p.id: (p.page_name or "") for p in pages.scalars().all()}
        result = await self.db.execute(
            select(ElementRepository).where(
                ElementRepository.project_id == pid,
                ElementRepository.status == "active")
        )
        els = result.scalars().all()
        out = []
        for e in els:
            d = e.to_dict()
            d["page_name"] = page_names.get(e.page_id)
            out.append(d)
        return {"version": 1, "exported_at": datetime.now(timezone.utc).isoformat(),
                "elements": out}

    async def import_elements(self, project_id: str, payload: Optional[Dict]) -> Dict:
        """导入元素 JSON。逐条走 create_element（复用 scope/page 校验），坏行跳过计数。

        跨项目 page_id 映射规则：导出数据里的 page_id 是源项目内部 ID，不可跨项目复用；
        page 级元素若带 page_name，则按名称匹配目标项目页面（找不到即跳过并记入 errors）；
        仅当元素未带 page_name 时才回退用原 page_id（同项目重导入场景）。
        仅消费 name/etype/text/scope/page_id/locators，其余字段（semantic_info/坐标等）不迁移。
        返回 {"imported": n, "skipped": m, "errors": [前5条原因]}。"""
        n = skipped = 0
        errors: List[str] = []
        rows = (payload or {}).get("elements") or []
        # 懒加载目标项目页面名映射（仅当存在带 page_name 的 page 级行）
        page_map: Dict = {}
        if any(isinstance(r, dict) and (r.get("scope") or "page") == "page"
               and r.get("page_name") for r in rows):
            from app.models.element import PageRepository
            result = await self.db.execute(
                select(PageRepository).where(
                    PageRepository.project_id == (_to_uuid(project_id) or project_id))
            )
            page_map = {p.page_name: p.id for p in result.scalars().all()}
        for item in rows:
            if not isinstance(item, dict) or not item.get("element_name"):
                skipped += 1
                continue
            try:
                ls = item.get("locator_strategies") or {}
                page_id = item.get("page_id")
                if (item.get("scope") or "page") == "page" and item.get("page_name"):
                    page_id = page_map.get(item["page_name"])
                    if page_id is None:
                        skipped += 1
                        errors.append(f"{item['element_name']}: 目标项目无同名页面「{item['page_name']}」")
                        continue
                await self.create_element(
                    project_id=project_id,
                    name=item["element_name"],
                    etype=item.get("element_type", "other"),
                    text=item.get("element_text") or "",
                    scope=item.get("scope", "page"),
                    page_id=page_id,
                    locators=ls.get("strategies", []) if isinstance(ls, dict) else ls,
                )
                n += 1
            except Exception as e:
                skipped += 1
                errors.append(f"{item.get('element_name')}: {e}")
                logger.warning(f"import element skipped: {e}")
        return {"imported": n, "skipped": skipped, "errors": errors[:5]}


async def verify_locator_on_page(page, locator: Dict) -> Dict:
    """单条定位器在已登录页面上验证。返回 {hit_count, score, error}。
    评分规则与抓取端 verify_and_score_locator 对齐：唯一+20 / 非唯一-20。"""
    value = locator.get("value", "")
    score = locator.get("score", 0) or 0
    try:
        if locator.get("type") == "xpath":
            found = await page.locator(f"xpath={value}").all()
        else:
            found = await page.locator(value).all()
        n = len(found)
        final = score + 20 if n == 1 else (score - 20 if n > 1 else 0)
        return {"hit_count": n, "score": max(final, 0), "error": None}
    except Exception as e:
        return {"hit_count": 0, "score": 0, "error": str(e)[:200]}
