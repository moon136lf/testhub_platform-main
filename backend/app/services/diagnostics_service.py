"""页面级 AI 诊断 (#5c): execution_id 取数 → 打包(TRANS-05) → 多模态 LLM → 诊断卡.

与 #4 ScriptDiagnoseService 并存: #4 是脚本级手动诊断(手填/四分类/重生成),
#5c 是页面级自动诊断(execution_id 取数/kimi2.6 看截图/new_locator).
诊断卡 append 到 ScriptAsset.ai_diagnosis (mode 区分, 见 spec §2.1).
"""
import json
import logging
import re
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionDetail, ExecutionRecord
from app.models.test_case import ScriptAsset

logger = logging.getLogger(__name__)

# 诊断 LLM 路线1: 硬编码 moonshot (kimi2.6 多模态, 同 #5b Level4); scope 配模型归 #10
DIAGNOSIS_PROVIDER = "moonshot"


class DiagnosticsService:
    def __init__(self, db: AsyncSession, gateway, storage):
        self.db = db
        self.gateway = gateway
        self.storage = storage

    async def analyze(self, exec_id: str, step: Optional[int] = None,
                      override: Optional[dict] = None) -> dict:
        """TRANS-05: 截图+DOM+堆栈+script_fragment 打包发 AI.

        入参 exec_id 是 ExecutionRecord.exec_id (unique, 前端从 session_id 拼
        exec-{session_id[:8]}, 与 /reports 同款标识).
        """
        detail = await self._get_fail_detail(exec_id, step)
        if not detail:
            raise ValueError(f"未找到失败记录: exec_id={exec_id}, step={step}")

        asset = None
        if detail.script_id:
            r = await self.db.execute(
                select(ScriptAsset).where(ScriptAsset.id == detail.script_id))
            asset = r.scalar_one_or_none()

        project_id = str(asset.project_id) if asset and asset.project_id else None

        # -- 打包四要素 (override 可覆盖) --
        error_type = detail.error_type or "script_error"
        error_msg = detail.error_msg or ""
        dom_snapshot = (detail.dom_snapshot or "")[:20000]  # 防 token 爆
        stack_trace = (detail.stack_trace or "")[:3000]
        script_fragment = self._build_fragment(asset, detail.step, detail.action)
        if override:
            error_type = override.get("error_type", error_type)
            error_msg = override.get("error_msg", error_msg)
            dom_snapshot = override.get("dom_snapshot", dom_snapshot)
            script_fragment = override.get("script_fragment", script_fragment)

        # 截图: storage 读 → base64 (复用 #5b 压缩); 失败降级无图
        img_b64 = self._load_screenshot_b64(detail.screenshot_url)

        # -- LLM 调用 --
        card = await self._call_llm(
            error_type=error_type, error_msg=error_msg, step=detail.step,
            action=detail.action, script_fragment=script_fragment,
            dom_snapshot=dom_snapshot, stack_trace=stack_trace, img_b64=img_b64,
            project_id=project_id,
        )

        # -- 落库: append 诊断卡 (数组化, mode=multimodal) --
        if asset is not None:
            asset.append_diagnosis(card, mode="multimodal")
            await self.db.flush()

        # -- 响应体 (§9.2.5 契约) --
        return {
            "diagnosis": card.get("diagnosis"),
            "suggestion": card.get("suggestion"),
            "new_locator": card.get("new_locator"),
            "confidence": card.get("confidence"),
            "apply_url": "/api/v1/diagnostics/apply",
            "card": card,
        }

    async def _get_fail_detail(self, exec_id: str, step: Optional[int]) -> Optional[ExecutionDetail]:
        r = await self.db.execute(
            select(ExecutionRecord).where(ExecutionRecord.exec_id == exec_id))
        rec = r.scalar_one_or_none()
        if not rec:
            return None
        q = select(ExecutionDetail).where(
            ExecutionDetail.execution_record_id == rec.id,
            ExecutionDetail.status == "fail")
        if step is not None:
            q = q.where(ExecutionDetail.step == step)
        q = q.order_by(ExecutionDetail.step).limit(1)
        r = await self.db.execute(q)
        return r.scalar_one_or_none()

    def _build_fragment(self, asset: Optional[ScriptAsset], step: Optional[int],
                        action: Optional[str]) -> str:
        """step_mapping[step] 拼 "{action} {impl} {value}"; 无则降级整段脚本."""
        if asset is None:
            return ""
        mapping = asset.step_mapping or []
        sm = next((m for m in mapping if m.get("step") == step), None)
        if sm:
            parts = [sm.get("action") or action or "", sm.get("impl") or "",
                     str(sm.get("value") or "")]
            return " ".join(p for p in parts if p).strip()
        return asset.content or ""

    def _load_screenshot_b64(self, screenshot_url: Optional[str]) -> Optional[str]:
        if not screenshot_url or self.storage is None:
            return None
        try:
            from app.services.self_heal_engine import SelfHealEngine
            raw = self.storage.get_object_bytes(screenshot_url)
            if not raw:
                return None
            return SelfHealEngine._screenshot_to_b64(raw)
        except Exception as e:
            logger.warning(f"diagnosis screenshot load failed: {e}")
            return None

    async def _call_llm(self, *, error_type: str, error_msg: str, step: Optional[int],
                        action: Optional[str], script_fragment: str,
                        dom_snapshot: str, stack_trace: str,
                        img_b64: Optional[str], project_id: Optional[str]) -> dict:
        prompt = f"""你是 UI 自动化测试诊断专家。脚本执行失败信息如下，请分析根因并给出修复建议。

失败步骤: 第 {step} 步 ({action or "unknown"})
错误类型: {error_type}
错误信息: {error_msg}
脚本片段: {script_fragment}
错误堆栈:
{stack_trace}

页面 DOM (截断):
{dom_snapshot}

请只输出一个 JSON 对象（不要 markdown 代码块，不要解释）：
{{"diagnosis": "根因分析，一句话", "suggestion": "修复建议，一句话", "new_locator": "若错误类型是 locate_failed 给出修复后的 Playwright 选择器字符串（如 #new-login-btn 或 text=\\"登录\\" 或 [aria-label=\\"登录\\"]，禁止 page.get_by_role(...) 等 Python API 表达式），否则 null", "confidence": 0到1之间的小数表示把握}}"""

        content_parts = [{"type": "text", "text": prompt}]
        if img_b64:
            content_parts.append({"type": "image_url",
                                  "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
        messages = [{"role": "user", "content": content_parts}]

        resp = await self.gateway.chat(
            messages, provider=DIAGNOSIS_PROVIDER,
            project_id=project_id, stage="diagnosis",
        )
        raw = resp.get("content") or ""
        card = self._parse_llm_card(raw, step=step, action=action,
                                    error_type=error_type, error_msg=error_msg)
        return card

    def _parse_llm_card(self, raw: str, *, step, action, error_type, error_msg) -> dict:
        """解析 LLM 输出 → 诊断卡. 非法 JSON 降级纯文本; new_locator 清洗防幻觉."""
        card: Dict[str, Any] = {
            "step": step, "action": action,
            "error_type": error_type, "error_msg": (error_msg or "")[:500],
        }
        data = None
        # 去 markdown 围栏再试
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                data = None
        if isinstance(data, dict):
            card["diagnosis"] = str(data.get("diagnosis") or "").strip() or "（AI 未给出根因分析）"
            card["suggestion"] = str(data.get("suggestion") or "").strip()
            conf = data.get("confidence")
            card["confidence"] = round(float(conf), 2) if isinstance(conf, (int, float)) else None
            locator = data.get("new_locator")
            cleaned = self._clean_locator(locator)
            if locator and cleaned is None:
                card["new_locator"] = None
                card["suggestion"] = (card["suggestion"] + "；注意：AI 给出的定位器无效，请参考建议手动修改。").strip("；;")
            else:
                card["new_locator"] = cleaned
        else:
            # 非法 JSON: 纯文本降级
            card["diagnosis"] = raw.strip()[:1000] or "（AI 无输出）"
            card["suggestion"] = ""
            card["new_locator"] = None
            card["confidence"] = None
        return card

    @staticmethod
    def _clean_locator(raw) -> Optional[str]:
        if not raw or not isinstance(raw, str):
            return None
        from app.services.self_heal_engine import SelfHealEngine
        return SelfHealEngine._clean_llm_locator(raw.strip())
