# backend/app/services/script_convert_service.py
"""转脚本编排: ConvertSession 生命周期 + 5 步调用 + SSE + Token。"""
import logging
from datetime import datetime

from sqlalchemy import select

from app.services.script_pipeline import (
    step0_normalize, step1_to_actions, step2_to_assertions,
    step3_match_locators, step4_generate_code, NormalizeError,
)
from app.services.script_validator import validate_script
from app.services.batch_naming import build_script_name
from app.models.test_case import ScriptAsset

logger = logging.getLogger(__name__)


class ConvertError(Exception):
    """单用例转换失败。"""


class ScriptConvertService:
    def __init__(self, db, gateway):
        self.db = db
        self.gateway = gateway

    async def convert_one(self, case: dict, sse, lookup, ai_optimize: bool) -> ScriptAsset:
        """转换单个用例 -> ScriptAsset (不写 DB, 由调用方决定)。"""
        case_id = case.get("id")
        await sse.send_message(type="system", stage="convert_script",
                               content=f"开始转换用例: {case.get('name','')}", progress=0.0)
        try:
            normalized = step0_normalize(case)
        except NormalizeError as e:
            await sse.send_message(type="error", stage="convert_script",
                                   content=f"用例 {case_id} 不可生成: {e}", progress=0.0)
            raise ConvertError(str(e))

        actions = await step1_to_actions(normalized, self.gateway)
        await sse.send_message(type="system", stage="convert_script",
                               content=f"生成 {len(actions)} 个动作意图", progress=0.3)

        asserts = await step2_to_assertions(normalized, self.gateway)
        await sse.send_message(type="system", stage="convert_script",
                               content=f"生成 {len(asserts)} 个断言计划", progress=0.5)

        with_loc = await step3_match_locators(
            actions, str(case.get("project_id")), lookup, ai_optimize, self.gateway)
        matched = sum(1 for w in with_loc if w.locator_status == "matched")
        await sse.send_message(type="system", stage="convert_script",
                               content=f"匹配元素库: {matched}/{len(with_loc)} 命中",
                               progress=0.7)

        gen = await step4_generate_code(normalized, with_loc, asserts, self.gateway)
        report = validate_script(gen.script, gen.step_mapping)
        if not report.all_pass():
            await sse.send_message(type="system", stage="convert_script",
                                   content=f"质量自检有项不过: {[c.name for c in report.checks if not c.passed]}",
                                   progress=0.9)

        status = "generated" if report.all_pass() else "draft"
        # #case-batch T4: 命名联动 — 有批次名用 批次名-自动化脚本HHmmss, 否则回退用例标题;
        # project_id+name 唯一约束, 撞名追加 -2/-3 (逐个查重)
        batch_name = case.get("batch_name")
        taken = set()
        if case.get("project_id"):
            base = (f"{batch_name}-自动化脚本{datetime.now().strftime('%H%M%S')}"
                    if batch_name else normalized.title)
            r = await self.db.execute(
                select(ScriptAsset.name).where(
                    ScriptAsset.project_id == case["project_id"],
                    ScriptAsset.name.like(f"{base}%")))
            taken = set(r.scalars().all())
        name = build_script_name(batch_name, normalized.title,
                                 datetime.now(), taken=taken)
        asset = ScriptAsset(
            case_id=case_id, project_id=case.get("project_id"),
            name=name, description=case.get("expected_result"),
            content=gen.script, version=1, status=status,
            category="uncategorized", module=case.get("module"),
            step_mapping=gen.step_mapping,
            locator_source=gen.locator_source, last_status="never_run",
            batch_name=batch_name,
            # 阶段3: 白盒生成的用例转脚本 → 自动纳入回归集
            for_regression=(case.get("source_type") == "whitescan"),
        )
        await sse.send_message(type="system", stage="convert_script",
                               content="转换完成，脚本已生成", progress=1.0,
                               tokens_used=self.gateway.tokens)
        return asset

    async def persist(self, asset: ScriptAsset):
        self.db.add(asset)
        await self.db.flush()
