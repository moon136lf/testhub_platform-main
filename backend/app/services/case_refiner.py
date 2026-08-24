"""E2E Case Refiner - rule + LLM hybrid engine.

Rule layer (free, no tokens) runs first; LLM layer (optional) supplements.
Rules adapted from docs/skills-reference/testcase-to-script-skill.md (case-layer).
"""
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# 永真断言黑名单（软断言词）— 这些动作不验证业务结果
FORBIDDEN_TAUTOLOGICAL_ASSERTIONS = ["观察", "查看", "验证", "检查", "确认", "看到", "显示", "观看", "浏览"]

# 模糊预期
AMBIGUOUS_EXPECTED = ["系统正常处理", "以实际为准", "正常", "页面正常", "操作成功"]

# 步骤动作映射 -> 是否可自动化
ACTION_VERB_MAP = {
    "观察": {"feasible": False, "fix": "转硬断言"},
    "查看": {"feasible": False, "fix": "转硬断言"},
    "验证": {"feasible": False, "fix": "转硬断言"},
    "检查": {"feasible": False, "fix": "转硬断言"},
    "确认": {"feasible": False, "fix": "转硬断言"},
    "打开": {"feasible": True},
    "进入": {"feasible": True},
    "访问": {"feasible": True},
    "点击": {"feasible": True},
    "输入": {"feasible": True},
    "选择": {"feasible": True},
    "勾选": {"feasible": True},
}

VISUAL_PATTERNS = ["美观", "布局好看", "对齐", "好看", "视觉效果"]

DIMENSIONS = ("步骤完整性", "断言增强", "异常路径补充", "数据准备清理", "可行性修正")


class CaseRefiner:
    """精修引擎：规则层免费先跑，LLM 层补语义。"""

    def refine_sync(self, case: Dict, page_elements: Optional[List] = None,
                    llm_enhance: bool = True) -> Dict:
        """同步精修。返回 refinement_report dict。"""
        suggestions: List[Dict] = []
        sid = 0

        def add(dim, issue, suggestion, severity="medium", step=None):
            nonlocal sid
            sid += 1
            suggestions.append({
                "id": f"S{sid}", "dimension": dim, "severity": severity,
                "target_step": step, "issue": issue, "suggestion": suggestion, "status": "pending",
            })

        # 维度1 步骤完整性
        suggestions.extend(self._check_steps_completeness(case, add))
        # 维度2 断言增强
        suggestions.extend(self._check_assertions(case))
        # 维度4 数据准备/清理
        suggestions.extend(self._check_data_setup(case))
        # 维度3 异常路径（LLM，此处占位简化）
        if llm_enhance:
            suggestions.extend(self._suggest_exception_paths_sync(case))
        # 维度5 可行性
        feas = self._assess_feasibility(case, page_elements)

        # normativity
        norm = {
            "steps_complete": len(case.get("steps", [])) > 0,
            "assertion_executable": not any("观察" in s.get("action", "") or "验证" in s.get("action", "")
                                            for s in case.get("steps", [])),
            "precondition_complete": bool(case.get("precondition")),
        }

        score = self._calculate_score(suggestions, norm)

        refined = dict(case)
        # apply feasibility fields to refined case representation
        refined["_feasibility_level"] = feas["feasibility_level"]
        refined["_cannot_automate_reason"] = feas["cannot_automate_reason"]

        return {
            "score": score,
            "refined_case": refined,
            "suggestions": suggestions,
            "normativity": norm,
            "reuse_level": "new",
            "feasibility_level": feas["feasibility_level"],
            "cannot_automate_reason": feas["cannot_automate_reason"],
        }

    # 维度1
    def _check_steps_completeness(self, case, add) -> List[Dict]:
        out = []
        steps = case.get("steps", [])
        if not steps:
            add("步骤完整性", "用例无任何步骤", "补充操作步骤", "high")
        for s in steps:
            action = s.get("action", "")
            if not action:
                add("步骤完整性", f"第{s.get('step')}步无动作描述", "补充动作", "high", s.get("step"))
        return out

    # 维度2
    def _check_assertions(self, case) -> List[Dict]:
        out = []
        for s in case.get("steps", []):
            action = s.get("action", "")
            for kw in FORBIDDEN_TAUTOLOGICAL_ASSERTIONS:
                if kw in action:
                    out.append({
                        "id": f"S{len(out)+1}", "dimension": "断言增强", "severity": "high",
                        "target_step": s.get("step"), "issue": f"步骤{s.get('step')}含软断言词「{kw}」",
                        "suggestion": "转为硬断言，验证操作导致的业务结果（如断言URL/文本/状态）",
                        "status": "pending",
                    })
                    break
        exp = case.get("expected_result", "")
        if exp in AMBIGUOUS_EXPECTED:
            out.append({
                "id": f"S{len(out)+1}", "dimension": "断言增强", "severity": "medium",
                "target_step": None, "issue": f"预期结果模糊:「{exp}」",
                "suggestion": "明确为可验证的业务结果", "status": "pending",
            })
        return out

    # 维度4
    def _check_data_setup(self, case) -> List[Dict]:
        out = []
        if not case.get("precondition"):
            out.append({
                "id": "S_d1", "dimension": "数据准备清理", "severity": "medium",
                "target_step": None, "issue": "缺少前置条件",
                "suggestion": "补充前置数据准备步骤", "status": "pending",
            })
        return out

    # 维度3（LLM 占位 — 真实 LLM 调用在异步/扩展时接入）
    def _suggest_exception_paths_sync(self, case) -> List[Dict]:
        return [{
            "id": "S_e1", "dimension": "异常路径补充", "severity": "low",
            "target_step": None, "issue": "主流程未覆盖异常分支",
            "suggestion": "补充密码错误/超时/空值等异常路径", "status": "pending",
        }]

    # 维度5
    def _assess_feasibility(self, case, page_elements: Optional[List]) -> Dict:
        for s in case.get("steps", []):
            action = s.get("action", "")
            if any(p in action for p in VISUAL_PATTERNS) or any(kw in action for kw in ("观察", "验证", "查看")):
                return {"feasibility_level": "manual",
                        "cannot_automate_reason": f"步骤「{action}」涉及视觉/软断言，无法稳定自动化"}
        if page_elements is None:
            return {"feasibility_level": "partial", "cannot_automate_reason": "元素库不可用，定位待确认"}
        return {"feasibility_level": "full", "cannot_automate_reason": ""}

    def _calculate_score(self, suggestions, norm) -> int:
        score = 100
        score -= sum(20 for s in suggestions if s["severity"] == "high")
        score -= sum(10 for s in suggestions if s["severity"] == "medium")
        score -= sum(5 for s in suggestions if s["severity"] == "low")
        if not norm["precondition_complete"]:
            score -= 10
        if not norm["assertion_executable"]:
            score -= 15
        return max(0, min(100, score))
