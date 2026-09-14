"""用例转脚本 5 阶段纯函数流水线 (skill Step0-4).

每阶段输入结构 -> 输出结构, LLM 通过注入的 gateway 调用, 可 mock。
"""
import json
import re
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
                 "create", "edit", "delete", "workflow_action", "input_captcha",
                 "captcha_recognize")


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
动作类型只能选: navigate/click/fill/select/check/create/edit/delete/workflow_action/captcha_recognize
映射规则:
- 点击X → click, target=X
- 输入/填写 X到Y → fill, target=Y, value=X (例: "输入test02到账号输入框" → fill, target=账号输入框, value=test02)
- 目标含"地址栏"或"URL"且值为 http 开头 → navigate, target 可为空, value=URL
- 步骤的 目标[]/数据[]/预期[] 分别对应 target/value/断言依据, 不得遗漏或编造
- 识别验证码 → captcha_recognize, target=验证码图片元素
- 输入/填写 验证码到输入框 → fill, target=验证码输入框, value=识别结果(引用上一步识别输出)
- 识别验证码与输入验证码是两个独立步骤，不得合并为一步
只输出 JSON 数组, 不要解释文字。

用例标题: {title}
步骤:
{steps}"""


def _fmt_steps(steps: List[Dict]) -> str:
    """完整输出步骤的目标/数据/预期，缺字段省略对应段。"""
    lines = []
    for s in steps:
        line = f"{s.get('step')}. {s.get('action','')}"
        if s.get("target"):
            line += f" 目标[{s['target']}]"
        if s.get("data"):
            line += f" 数据[{s['data']}]"
        elif s.get("value"):
            line += f" 数据[{s['value']}]"
        if s.get("expected"):
            line += f" 预期[{s['expected']}]"
        lines.append(line)
    return "\n".join(lines)


def _navigate_postprocess(actions: List[ActionIntent]) -> List[ActionIntent]:
    """确定性兜底：fill + 目标含地址栏/URL + value 为 http 开头 → 强制 navigate。"""
    for a in actions:
        if (a.action == "fill" and a.target and ("地址栏" in a.target or "url" in a.target.lower())
                and a.value and str(a.value).lower().startswith("http")):
            a.action = "navigate"
            a.target = None
    return actions


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
    return _navigate_postprocess(actions)


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


ASSERTION_RULES_DOC = """预期结果→断言类型模板库（方案V1阶段6）：
- 显示/输入了X 且测试数据=X → expect_value
- 进入/跳转/URL → expect_url（从 value URL 提取 path）
- 密文/密码 → expect_attribute(type==password)
- 成功/欢迎/提示 + 点击 → expect_toast
- 其他含引号或"包含"的明确文案 → expect_text
推断不出 → None（走 LLM 兜底）"""


def infer_assertion_rule(target: Optional[str], value: str, expected_text: str, action: str):
    """确定性断言推断。返回 {assertion_type, expected, target} 或 None。"""
    if not expected_text:
        return None
    t = expected_text

    if "密文" in t or ("密码" in t and "显示" in t):
        return {"assertion_type": "expect_attribute", "expected": "password", "target": target}

    if action == "navigate" or any(k in t for k in ("进入", "跳转", "URL", "地址")):
        # 只有 value 是合法 URL 才生成 URL 断言，否则 None 走 LLM 兜底
        if not (value and value.startswith("http")):
            return None
        # 从测试数据 URL 提取 path 尾段作期望
        path = value.rstrip("/").rsplit("/", 1)[-1] or value
        return {"assertion_type": "expect_url", "expected": path, "target": ""}

    if value and value in t and ("显示" in t or "输入" in t):
        return {"assertion_type": "expect_value", "expected": value, "target": target}

    if action == "click" and any(k in t for k in ("成功", "欢迎", "提示")):
        return {"assertion_type": "expect_toast", "expected": t, "target": ""}

    if "包含" in t or "显示" in t:
        # 提取引号内文案，否则整句
        m = re.search(r"[“\"'](.+?)[”\"']", t)
        return {"assertion_type": "expect_text", "expected": m.group(1) if m else t, "target": target}

    return None


def _is_tautological(a: dict) -> bool:
    target = (a.get("target") or "") + (a.get("expected") or "")
    return any(kw in target for kw in TAUTOLOGICAL_KEYWORDS)


async def step2_to_assertions(case: NormalizedCase, gateway: LLMGatewayProto) -> List[AssertionPlan]:
    """Step2: 预期 → 断言计划。规则模板库前置，未命中行走 LLM 兜底，后置永真断言校验。"""
    plans = []
    unmatched = []
    for s in case.steps:
        action = s.get("action", "")
        hit = infer_assertion_rule(
            s.get("target") or None, s.get("value", ""),
            (s.get("expected") or "").strip(), action)
        if hit:
            plans.append(AssertionPlan(
                step=int(s.get("step", 0)),
                assertion_type=hit["assertion_type"],
                target=hit.get("target") or None,
                expected=hit.get("expected"),
                is_valid=True,
            ))
        else:
            unmatched.append(s)

    if unmatched:
        prompt = STEP2_PROMPT.format(
            expected=case.expected_result,
            step_expected="\n".join(f"{s.get('step')}. {s.get('expected','')}" for s in unmatched),
        )
        resp = await gateway.chat([{"role": "user", "content": prompt}])
        items = parse_llm_json(resp["content"])
    else:
        items = []
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
    plans.sort(key=lambda p: p.step)
    return plans


@dataclass
class ActionWithLocator:
    step: int
    action: str
    target: Optional[str]
    value: Optional[str]
    locator: Optional[str] = None
    locator_status: str = "none_draft"  # matched / pending_confirm / none_draft
    locator_source: str = "none_draft"  # element_library / ai_generated / mixed / none_draft
    element_id: Optional[str] = None
    element_name: Optional[str] = None
    match_score: Optional[float] = None
    match_level: str = ""  # L1/L2/low（绑定事件与溯源透传）


class CandidatesLookupProto(Protocol):
    """评分管线协议: find_candidates(project_id, target, intent_action, page_id) -> List[Dict]。"""
    async def find_candidates(self, project_id: str, target: str,
                              intent_action: Optional[str] = None,
                              page_id: Optional[str] = None) -> List[Dict]: ...


STEP3_PICK_PROMPT = """你是元素选择器。从候选元素中为用例步骤目标选出最匹配的一个，只输出 JSON。
目标: {target}
候选(编号|别名|定位|类型):
{candidates}
输出格式: {{"pick": 编号}}，都不合适则 {{"pick": null}}。"""


async def _ai_pick_element(target: str, candidates: List[Dict], gateway) -> Optional[Dict]:
    """Midscene 模式：LLM 只从候选中选，不生成定位器。"""
    lines = "\n".join(
        f"{i}|{c.get('element_name','')}|{c.get('locator','')}|{c.get('match_level','')}"
        for i, c in enumerate(candidates))
    resp = await gateway.chat([{"role": "user", "content": STEP3_PICK_PROMPT.format(target=target, candidates=lines)}])
    import json as _json
    try:
        m = re.search(r"\{[^}]*\}", resp["content"])
        pick = _json.loads(m.group(0)).get("pick") if m else None
        if isinstance(pick, int) and 0 <= pick < len(candidates):
            return candidates[pick]
    except (ValueError, AttributeError):
        pass
    return None


async def step3_match_locators(
    actions: List[ActionIntent],
    project_id: str,
    lookup: CandidatesLookupProto,
    ai_optimize: bool,
    gateway: Optional[LLMGatewayProto],
) -> List[ActionWithLocator]:
    """Step3 方案V1：L1/L2 评分命中→绑定；未命中→L3 候选单选（可关）→draft。"""
    results: List[ActionWithLocator] = []
    matched = 0
    ai_used = False
    for a in actions:
        picked = None
        # intent 动作归一化为元素类型意图（fill→input/check→click），供评分类型加分与候选过滤
        intent = {"fill": "input", "check": "click"}.get(a.action, a.action)
        cands = await lookup.find_candidates(project_id, a.target, intent_action=intent) if a.target else []
        top = cands[0] if cands and cands[0].get("match_level") in ("L1", "L2") else None
        if top:
            status, loc = "matched", top["locator"]
            matched += 1
        elif ai_optimize and gateway is not None and cands:
            picked = await _ai_pick_element(a.target, cands, gateway)
            if picked:
                status, loc = "pending_confirm", picked["locator"]
                matched += 1
                ai_used = True
            else:
                status, loc = "none_draft", None
        else:
            status, loc = "none_draft", None
        bound = top or picked or {}
        results.append(ActionWithLocator(
            step=a.step, action=a.action, target=a.target, value=a.value,
            locator=loc, locator_status=status,
            element_id=bound.get("element_id"),
            element_name=bound.get("element_name"),
            match_score=bound.get("score"),
            match_level=bound.get("match_level", ""),
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
            "element_id": getattr(a, "element_id", None),
            "match_level": getattr(a, "match_level", "") or None,
            "match_score": getattr(a, "match_score", None),
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
