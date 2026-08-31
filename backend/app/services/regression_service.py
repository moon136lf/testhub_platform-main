"""回归集服务 (#8): 识别数据组装 + upsert + 成员管理 + 统计.

规则打分在 regression_rules (纯函数); 本服务负责 ORM→dict 组装与落库.
upsert 语义 (spec 偏差 I): manual 行不动 actual_included; ai 行跟随最新识别.
"""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionDetail
from app.models.regression import RegressionSet
from app.models.test_case import ScriptAsset, TestCase, TestPoint
from app.services.regression_rules import score_script, INCLUDED_THRESHOLD

logger = logging.getLogger(__name__)

PASS_HISTORY_WINDOW = 10  # R2/R5 取近 N 次 step=0 结果


def _uuid(v):
    """str/UUID 双接受; 非法值原样返回 (FakeDB/无 DB 场景不炸)."""
    try:
        return v if isinstance(v, UUID) else UUID(str(v))
    except (ValueError, AttributeError):
        return v


class RegressionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- 识别 ----

    async def identify_project(self, project_id: str) -> dict:
        """全量 confirmed 脚本重算识别 (REG-02, /identify)."""
        result = await self.db.execute(
            select(ScriptAsset).where(
                ScriptAsset.project_id == _uuid(project_id),
                ScriptAsset.status == "confirmed"))
        scripts = result.scalars().all()
        suggested = 0
        for s in scripts:
            row = await self._identify_one(s)
            if row and row.ai_suggested:
                suggested += 1
        return {"identified": len(scripts), "suggested_count": suggested}

    async def identify_for_script(self, project_id: str, script_id: str) -> None:
        """单脚本识别 (#4 confirm hook). 异常由调用方隔离 (不阻塞 confirm)."""
        result = await self.db.execute(
            select(ScriptAsset).where(ScriptAsset.id == _uuid(script_id)))
        script = result.scalar_one_or_none()
        if script:
            await self._identify_one(script)

    async def _identify_one(self, script: ScriptAsset) -> Optional[RegressionSet]:
        data = await self._assemble(script)
        # T2 契约: score_script 返回 (score: int, reason: str), included 由调用方判定
        score, reason = score_script(data)
        included = score >= INCLUDED_THRESHOLD
        return await self.upsert_member(str(script.project_id), script.id,
                                        included=included, reason=reason)

    async def _assemble(self, script: ScriptAsset) -> dict:
        """ORM → score_script 输入 dict (T2 契约, recent_runs 旧→新)."""
        # R1/R3 数据: TestCase.priority + TestPoint.type_label
        priority, type_label = "P1", None
        if script.case_id:
            r = await self.db.execute(select(TestCase).where(TestCase.id == script.case_id))
            case = r.scalar_one_or_none()
            if case:
                priority = case.priority or "P1"
                if case.point_id:
                    pr = await self.db.execute(
                        select(TestPoint).where(TestPoint.id == case.point_id))
                    point = pr.scalar_one_or_none()
                    if point:
                        type_label = point.type_label

        # R2/R5 数据: 近 N 次 step=0 结果 (查询倒序取最近, reversed 转旧→新)
        er = await self.db.execute(
            select(ExecutionDetail)
            .where(ExecutionDetail.script_id == script.id,
                   ExecutionDetail.step == 0)
            .order_by(ExecutionDetail.created_at.desc())
            .limit(PASS_HISTORY_WINDOW))
        details = er.scalars().all()
        recent_runs = [d.status == "pass" for d in reversed(details)]

        # R4 数据: 同 module 是否已有 included
        module_has_included = False
        if script.module:
            mr = await self.db.execute(
                select(RegressionSet.id)
                .join(ScriptAsset, ScriptAsset.id == RegressionSet.script_id)
                .where(RegressionSet.project_id == script.project_id,
                       RegressionSet.actual_included.is_(True),
                       ScriptAsset.module == script.module,
                       ScriptAsset.id != script.id)
                .limit(1))
            module_has_included = mr.scalar_one_or_none() is not None

        # R6 数据
        sm = script.step_mapping or []
        elements = {m.get("element_name") for m in sm if m.get("element_name")}

        return {
            "priority": priority,
            "category": script.category,
            "module": script.module,
            "module_has_included": module_has_included,
            "type_label": type_label,
            "step_count": len(sm),
            "element_count": len(elements),
            "recent_runs": recent_runs,
        }

    # ---- upsert / 成员管理 ----

    async def upsert_member(self, project_id: str, script_id: UUID,
                            included: bool, reason: str) -> RegressionSet:
        r = await self.db.execute(
            select(RegressionSet).where(
                RegressionSet.project_id == _uuid(project_id),
                RegressionSet.script_id == script_id))
        row = r.scalar_one_or_none()
        if row is None:
            row = RegressionSet(project_id=_uuid(project_id), script_id=script_id,
                                ai_suggested=included, ai_reason=reason or None,
                                actual_included=included, include_source="ai")
            self.db.add(row)
        else:
            row.ai_suggested = included
            row.ai_reason = reason or None
            if row.include_source != "manual":
                # ai 行跟随最新识别; manual 行人工调整优先 (偏差 I)
                row.actual_included = included
                row.include_source = "ai"
        await self.db.flush()
        return row

    async def set_member(self, project_id: str, script_id: UUID, action: str) -> None:
        """REG-03 手动调整: add/remove, include_source=manual (识别不再覆盖)."""
        r = await self.db.execute(
            select(RegressionSet).where(
                RegressionSet.project_id == _uuid(project_id),
                RegressionSet.script_id == script_id))
        row = r.scalar_one_or_none()
        if row is None:
            row = RegressionSet(project_id=_uuid(project_id), script_id=script_id,
                                ai_suggested=False, actual_included=(action == "add"),
                                include_source="manual")
            self.db.add(row)
        else:
            row.actual_included = (action == "add")
            row.include_source = "manual"
        await self.db.flush()

    # ---- 统计 / 列表 ----

    async def get_stats(self, project_id: str) -> dict:
        """统计卡: included=true ⋈ script_asset.last_status 聚合 (页面加载即有值)."""
        result = await self.db.execute(
            select(ScriptAsset)
            .join(RegressionSet, RegressionSet.script_id == ScriptAsset.id)
            .where(RegressionSet.project_id == _uuid(project_id),
                   RegressionSet.actual_included.is_(True)))
        scripts = result.scalars().all()
        total = len(scripts)
        passed = sum(1 for s in scripts if s.last_status == "passed")
        failed = sum(1 for s in scripts if s.last_status == "failed")
        rate = round(passed / total * 100, 1) if total else 0
        return {"total": total, "passed": passed, "failed": failed, "pass_rate": rate}

    async def list_view(self, project_id: str, category: Optional[str] = None,
                        keyword: Optional[str] = None) -> list:
        """管理视图: 全量 confirmed 脚本 LEFT JOIN regression_set (含未纳入行)."""
        q = (
            select(ScriptAsset, RegressionSet)
            .outerjoin(RegressionSet, RegressionSet.script_id == ScriptAsset.id)
            .where(ScriptAsset.project_id == _uuid(project_id),
                   ScriptAsset.status == "confirmed")
        )
        if category:
            q = q.where(ScriptAsset.category == category)
        if keyword:
            q = q.where(ScriptAsset.name.ilike(f"%{keyword}%"))
        q = q.order_by(ScriptAsset.name)
        result = await self.db.execute(q)
        items = []
        for s, reg in result.all():
            items.append({
                "script": s.to_dict(),
                "ai_suggested": bool(reg.ai_suggested) if reg else False,
                "ai_reason": reg.ai_reason if reg else None,
                "actual_included": bool(reg.actual_included) if reg else False,
                "include_source": reg.include_source if reg else None,
            })
        return items
