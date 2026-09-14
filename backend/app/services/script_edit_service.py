"""脚本编辑服务（阶段2/方案V1阶段4）：步骤化编辑器保存链路。

save_steps = 行式步骤 → step_codegen.generate_script 生成 Playwright 脚本
→ 写 ScriptAsset.content + step_mapping（复用字段存编辑器原始行）+ version+1
→ 步骤行同步落 script_steps 表（先删后插全量替换）
→ 人工绑定（element_id + case_target_text）回写 synonym。"""
import logging
from typing import Dict, List
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_case import ScriptAsset
from app.models.script_step import ScriptStep
from app.services.step_codegen import generate_script

logger = logging.getLogger(__name__)


def _to_uuid(v):
    if not v:
        return None
    try:
        return UUID(str(v))
    except (ValueError, AttributeError, TypeError):
        return None


class ScriptEditService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._element_service = None

    @property
    def element_service(self):
        if self._element_service is None:
            from app.services.element_service import ElementService
            self._element_service = ElementService(self.db)
        return self._element_service

    async def write_synonym(self, element_id: str, text: str, source: str = "manual_binding") -> bool:
        """回写同义词（委托 ElementService.write_synonym，同事务 flush 不 commit）。"""
        return await self.element_service.write_synonym(element_id, text, source=source)

    async def save_steps(self, script_id: str, title: str, steps: List[Dict]) -> ScriptAsset:
        """保存步骤化编辑。codegen 的 ValueError（空步骤/未知操作/缺 target）原样上抛。"""
        asset = await self.db.get(ScriptAsset, UUID(script_id))
        if not asset:
            raise ValueError("脚本不存在")
        if not steps:
            raise ValueError("至少需要一个步骤")
        asset.content = generate_script(title or asset.name, steps)
        asset.step_mapping = steps
        asset.version = (asset.version or 1) + 1

        # script_steps 行：先删后插（脚本内步骤全量替换）
        await self.db.execute(sa_delete(ScriptStep).where(ScriptStep.script_id == asset.id))
        rows = []
        for i, s in enumerate(steps, start=1):
            element_uuid = _to_uuid(s.get("element_id"))
            row = ScriptStep(
                script_id=asset.id, step_no=i,
                case_step_no=s.get("case_step_no"),
                action=s.get("action", ""),
                element_id=element_uuid,
                extra_element_id=_to_uuid(s.get("extra_element_id")),
                target=s.get("target", ""),
                value=s.get("value", ""),
                assertion=s.get("expected", ""),
                assertion_type=s.get("assertion_type", ""),
            )
            rows.append(row)
            # 人工绑定回写 synonym（有 element_id 且带用例目标词原文）
            if element_uuid and s.get("case_target_text"):
                try:
                    await self.write_synonym(
                        str(element_uuid), s["case_target_text"], source="manual_binding")
                except Exception:
                    logger.warning("synonym 回写失败，不阻断保存", exc_info=True)
        self.db.add_all(rows)
        await self.db.commit()
        # updated_at 有 server onupdate，commit 后属性过期；不 refresh 的话端点 to_dict()
        # 会同步 lazy load → asyncpg 下 MissingGreenlet 崩（真浏览器验收问题1）
        await self.db.refresh(asset)
        return asset
