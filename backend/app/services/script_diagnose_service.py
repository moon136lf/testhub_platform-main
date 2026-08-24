# backend/app/services/script_diagnose_service.py
"""调试修复: skill 5.2 四分类归因 + 失败步骤重生成。"""
from typing import Optional


DATA_ENV_KEYWORDS = ("重复", "已存在", "唯一", "duplicate", "already exists", "unique")


def classify_failure(error_type: Optional[str], error_msg: str,
                     failed_step: Optional[int]) -> dict:
    """skill 5.2 四分类:
    - script_problem (定位/超时/脚本错误) -> 可改
    - page_bug (断言值不符) -> 不可改, xfail
    - data_env (重复/已存在/唯一) -> 不可改, 硬停
    - ambiguous (信息不足) -> 不可改
    """
    msg = error_msg or ""
    if any(kw in msg for kw in DATA_ENV_KEYWORDS):
        return _card("data_env", False, "数据/环境问题，硬停", failed_step, error_type, error_msg)
    if error_type == "assertion_failed":
        return _card("page_bug", False, "断言值不符，页面Bug，标xfail", failed_step, error_type, error_msg)
    if error_type in ("locate_failed", "timeout", "script_error"):
        return _card("script_problem", True, "脚本问题，可改", failed_step, error_type, error_msg)
    return _card("ambiguous", False, "信息不足，建议补DOM/截图", failed_step, error_type, error_msg)


def _card(category, can_fix, reason, failed_step, error_type, error_msg, **extra):
    d = {"category": category, "can_fix": can_fix, "reason": reason,
         "failed_step": failed_step, "error_type": error_type, "error_msg": error_msg,
         "suggestion": ""}
    d.update(extra)
    return d


class ScriptDiagnoseService:
    def __init__(self, gateway):
        self.gateway = gateway

    async def diagnose(self, error_type, error_msg, script_fragment,
                       failed_step=None, screenshot_url=None, dom_snapshot=None):
        card = classify_failure(error_type, error_msg, failed_step)
        card["screenshot_url"] = screenshot_url
        if card["can_fix"] and self.gateway is not None and failed_step:
            card["revised_step"] = await self._regen_step(error_type, error_msg, script_fragment, failed_step)
            card["suggestion"] = f"已重生成步骤 {failed_step} 代码"
        elif card["can_fix"]:
            card["revised_step"] = None
            card["suggestion"] = "可改但缺少 gateway 或 failed_step"
        else:
            card["revised_step"] = None
            card["suggestion"] = card["reason"]
        return card

    async def _regen_step(self, error_type, error_msg, script_fragment, failed_step):
        prompt = f"修复第 {failed_step} 步脚本。错误类型: {error_type}, 错误: {error_msg}。只输出修复后的代码片段:\n{script_fragment}"
        resp = await self.gateway.chat([{"role": "user", "content": prompt}])
        return resp["content"].strip()
