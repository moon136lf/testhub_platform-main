"""用例转脚本 5 阶段纯函数流水线 (skill Step0-4).

每阶段输入结构 -> 输出结构, LLM 通过注入的 gateway 调用, 可 mock。
"""
import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Protocol


class NormalizeError(Exception):
    """用例无法标准化 (steps/expected 缺失)."""


@dataclass
class NormalizedCase:
    case_id: str
    title: str
    steps: List[Dict[str, Any]]
    expected_result: str


VALID_ACTIONS = ("navigate", "click", "fill", "select", "check",
                 "create", "edit", "delete", "workflow_action")


@dataclass
class ActionIntent:
    step: int
    action: str
    target: Optional[str] = None
    value: Optional[str] = None


class LLMGatewayProto(Protocol):
    """LLM 网关协议: chat(messages) -> {"content": str, "tokens": int}."""
    async def chat(self, messages: List[Dict], **kw) -> Dict: ...


STEP1_PROMPT = """你是测试脚本转换器。把测试步骤转成结构化动作意图, 输出 JSON 数组。
每项: {{"step": int, "action": 动作类型, "target": 目标元素或页面, "value": 输入值}}
动作类型只能选: navigate/click/fill/select/check/create/edit/delete/workflow_action
只输出 JSON 数组, 不要解释文字。

用例标题: {title}
步骤:
{steps}"""


def _fmt_steps(steps: List[Dict]) -> str:
    return "\n".join(f"{s.get('step')}. {s.get('action','')}" for s in steps)


def step0_normalize(case: Dict[str, Any]) -> NormalizedCase:
    """Step0: 用例标准化。缺失 steps/expected 阻塞；缺失 title 用步骤摘要生成。"""
    steps = case.get("steps") or []
    expected = (case.get("expected_result") or "").strip()
    if not steps:
        raise NormalizeError("用例缺少步骤，无法生成脚本")
    if not expected:
        raise NormalizeError("用例缺少预期结果，无法生成脚本")

    title = (case.get("name") or "").strip()
    if not title:
        actions = [s.get("action", "") for s in steps[:3]]
        title = " / ".join(a for a in actions if a) or "未命名用例"

    return NormalizedCase(
        case_id=case.get("id", ""),
        title=title,
        steps=steps,
        expected_result=expected,
    )


async def step1_to_actions(case: NormalizedCase, gateway: LLMGatewayProto) -> List[ActionIntent]:
    """Step1: 步骤 → 动作意图 (LLM)."""
    prompt = STEP1_PROMPT.format(title=case.title, steps=_fmt_steps(case.steps))
    resp = await gateway.chat([{"role": "user", "content": prompt}])
    raw = resp["content"].strip()
    items = json.loads(raw)
    actions = []
    for it in items:
        action = it.get("action")
        if action not in VALID_ACTIONS:
            raise ValueError(f"非法动作类型: {action}")
        actions.append(ActionIntent(
            step=int(it["step"]),
            action=action,
            target=it.get("target"),
            value=it.get("value"),
        ))
    actions.sort(key=lambda a: a.step)
    return actions


@dataclass
class AssertionPlan:
    step: int
    assertion_type: str  # toast_message/row_visible/status_changed/field_value/dialog_closed/ambiguous
    target: Optional[str] = None
    expected: Optional[str] = None
    is_valid: bool = True


VALID_ASSERTION_TYPES = ("toast_message", "row_visible", "status_changed",
                         "field_value", "dialog_closed", "ambiguous")

# 永真断言黑名单 (skill 3.3): "验证按钮/菜单可见" 等不验证业务结果
TAUTOLOGICAL_KEYWORDS = ("按钮可见", "菜单可见", "页面可见", "元素可见")


STEP2_PROMPT = """你是测试脚本转换器。把预期结果转成断言计划, 输出 JSON 数组。
每项: {{"step": int, "assertion_type": 类型, "target": 目标, "expected": 期望值, "is_valid": bool}}
类型只能选: toast_message/row_visible/status_changed/field_value/dialog_closed/ambiguous
is_valid=false 当断言不验证业务结果(只验证固定元素可见)。
模糊预期(如"系统正常处理")用 ambiguous 类型, is_valid=false。
只输出 JSON 数组。

预期结果: {expected}
步骤预期:
{step_expected}"""


def _fmt_step_expected(steps: List[Dict]) -> str:
    return "\n".join(f"{s.get('step')}. {s.get('expected','')}" for s in steps)


def _is_tautological(a: dict) -> bool:
    target = (a.get("target") or "") + (a.get("expected") or "")
    return any(kw in target for kw in TAUTOLOGICAL_KEYWORDS)


async def step2_to_assertions(case: NormalizedCase, gateway: LLMGatewayProto) -> List[AssertionPlan]:
    """Step2: 预期 → 断言计划 (LLM), 后置永真断言校验。"""
    prompt = STEP2_PROMPT.format(
        expected=case.expected_result,
        step_expected=_fmt_step_expected(case.steps),
    )
    resp = await gateway.chat([{"role": "user", "content": prompt}])
    items = json.loads(resp["content"].strip())
    plans = []
    for it in items:
        atype = it.get("assertion_type")
        if atype not in VALID_ASSERTION_TYPES:
            raise ValueError(f"非法断言类型: {atype}")
        is_valid = bool(it.get("is_valid", True))
        if _is_tautological(it):
            is_valid = False
        if atype == "ambiguous":
            is_valid = False
        plans.append(AssertionPlan(
            step=int(it["step"]),
            assertion_type=atype,
            target=it.get("target"),
            expected=it.get("expected"),
            is_valid=is_valid,
        ))
    return plans
