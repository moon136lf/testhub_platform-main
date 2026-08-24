"""用例转脚本 5 阶段纯函数流水线 (skill Step0-4).

每阶段输入结构 -> 输出结构, LLM 通过注入的 gateway 调用, 可 mock。
"""
from dataclasses import dataclass
from typing import List, Dict, Any


class NormalizeError(Exception):
    """用例无法标准化 (steps/expected 缺失)."""


@dataclass
class NormalizedCase:
    case_id: str
    title: str
    steps: List[Dict[str, Any]]
    expected_result: str


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
