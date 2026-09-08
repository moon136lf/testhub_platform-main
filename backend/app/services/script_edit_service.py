"""脚本编辑服务（阶段2）：步骤化编辑器保存链路。

save_steps = 行式步骤 → step_codegen.generate_script 生成 Playwright 脚本
→ 写 ScriptAsset.content + step_mapping（复用字段存编辑器原始行）+ version+1。"""
import logging
from typing import Dict, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_case import ScriptAsset
from app.services.step_codegen import generate_script

logger = logging.getLogger(__name__)


class ScriptEditService:
    def __init__(self, db: AsyncSession):
        self.db = db

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
        await self.db.commit()
        return asset
