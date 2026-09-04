"""用例转脚本 5 阶段纯函数流水线 (skill Step0-4).

每阶段输入结构 -> 输出结构, LLM 通过注入的 gateway 调用, 可 mock。
"""
import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Protocol
from app.core.json_utils import parse_llm_json


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
    items = parse_llm_json(raw)
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
    items = parse_llm_json(resp["content"])
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


class ElementLookupProto(Protocol):
    """元素库协议: find(project_id, target) -> locator 字符串或 None。"""
    async def find(self, project_id: str, target: str) -> Optional[str]: ...


@dataclass
class ActionWithLocator:
    step: int
    action: str
    target: Optional[str]
    value: Optional[str]
    locator: Optional[str] = None
    locator_status: str = "none_draft"  # matched / pending_confirm / none_draft
    locator_source: str = "none_draft"  # element_library / ai_generated / mixed / none_draft


STEP3_AI_PROMPT = """你是定位器生成器。为 UI 元素生成 Playwright 定位器, 优先 get_by_role > get_by_text > get_by_label > get_by_placeholder > css。
只输出一个定位器字符串(如 page.get_by_role("button", name="登录")), 不要解释。
元素描述: {target}"""


async def _ai_generate_locator(target: str, gateway: LLMGatewayProto) -> str:
    resp = await gateway.chat([{"role": "user", "content": STEP3_AI_PROMPT.format(target=target)}])
    return resp["content"].strip()


async def step3_match_locators(
    actions: List[ActionIntent],
    project_id: str,
    lookup: ElementLookupProto,
    ai_optimize: bool,
    gateway: Optional[LLMGatewayProto],
) -> List[ActionWithLocator]:
    """Step3: 动作意图 + 元素库 → 绑 locator (TRANS-01)。命中用库, 未命中 AI 生成或 draft。"""
    results: List[ActionWithLocator] = []
    matched = 0
    ai_used = False
    for a in actions:
        loc = await lookup.find(project_id, a.target) if a.target else None
        if loc:
            status = "matched"
            matched += 1
        elif ai_optimize and gateway is not None and a.target:
            loc = await _ai_generate_locator(a.target, gateway)
            status = "pending_confirm"
            ai_used = True
            matched += 1
        else:
            loc = None
            status = "none_draft"
        results.append(ActionWithLocator(
            step=a.step, action=a.action, target=a.target, value=a.value,
            locator=loc, locator_status=status,
        ))
    total = len(results)
    if matched == 0:
        source = "none_draft"
    elif ai_used and matched < total:
        source = "mixed"
    elif ai_used:
        source = "ai_generated"
    elif matched < total:
        source = "mixed"
    else:
        source = "element_library"
    for r in results:
        r.locator_source = source
    return results


@dataclass
class GenerateResult:
    script: str
    step_mapping: List[Dict[str, Any]]
    locator_source: str


STEP4_PROMPT = """生成 Python + Playwright + pytest 测试函数。规则:
- 定位器优先级: get_by_role > get_by_text > get_by_label > get_by_placeholder > css
- 禁止 click/fill 用 .first/.nth/.last
- 禁止永真断言(只验证按钮可见)
- 等待优先 expect 自带 > wait_for_response > wait_for(state) > wait_for_load_state(networkidle) > wait_for_timeout(<=500ms 仅动画)
- 无定位器的步骤用注释占位: # TODO: 待确认定位器
只输出代码, 不要 markdown 围栏。

用例标题: {title}
动作与定位器:
{actions}
断言:
{asserts}"""


def _fmt_actions(actions: List[ActionWithLocator]) -> str:
    lines = []
    for a in actions:
        loc = a.locator or "(待确认)"
        lines.append(f"{a.step}. {a.action} {a.target or ''} 值={a.value or ''} locator={loc}")
    return "\n".join(lines)


def _fmt_asserts(asserts: List[AssertionPlan]) -> str:
    return "\n".join(f"{a.step}. {a.assertion_type} {a.target or ''} 期望={a.expected or ''}" for a in asserts)


def _build_step_mapping(actions: List[ActionWithLocator], asserts: List[AssertionPlan], script: str) -> List[Dict[str, Any]]:
    # 按 step 索引断言
    assert_by_step = {a.step: a for a in asserts}
    mapping = []
    for a in actions:
        impl = a.locator or ""
        status = "ok" if (a.locator and a.locator in script) else "blocked"
        ap = assert_by_step.get(a.step)
        mapping.append({
            "step": a.step,
            "case_req": f"{a.action} {a.target or ''}",
            "impl": impl,
            "status": status,
            "element_name": a.target,
            "page_name": getattr(a, "page_name", None),
            "action": a.action,
            "value": a.value,
            "assertion": {
                "type": ap.assertion_type,
                "target": ap.target,
                "expected": ap.expected,
                "is_valid": ap.is_valid,
            } if ap else None,
        })
    return mapping


async def step4_generate_code(
    case: NormalizedCase,
    actions: List[ActionWithLocator],
    asserts: List[AssertionPlan],
    gateway: LLMGatewayProto,
) -> GenerateResult:
    """Step4: 代码生成 + 步骤对照表 (LLM 拼装)。"""
    prompt = STEP4_PROMPT.format(
        title=case.title,
        actions=_fmt_actions(actions),
        asserts=_fmt_asserts(asserts),
    )
    resp = await gateway.chat([{"role": "user", "content": prompt}])
    script = resp["content"].strip()
    step_mapping = _build_step_mapping(actions, asserts, script)
    source = actions[0].locator_source if actions else "none_draft"
    return GenerateResult(script=script, step_mapping=step_mapping, locator_source=source)
