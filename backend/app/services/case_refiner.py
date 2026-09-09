"""E2E Case Refiner - rule + LLM hybrid engine.

Rule layer (free, no tokens) runs first; LLM layer (optional) supplements.
Rules adapted from docs/skills-reference/testcase-to-script-skill.md (case-layer).
"""
import json
import logging
from typing import Dict, List, Optional, Any

from app.core.json_utils import parse_llm_json

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
        """同步精修。返回 refinement_report dict。

        异常路径维度若 llm_enhance=False 则跳过（LLM 建议为 async）。
        """
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
        # 维度3 异常路径：LLM 版为 async，由 refine_case 调用后合并
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
        # 结构性建议自动落地：缺前置条件 → 生成默认前置（规则层免费补全，
        # 应用建议后用户能看到实际变化，而非只改了建议状态）
        if not refined.get("precondition"):
            refined["precondition"] = "已登录系统并进入相关页面，基础数据已就绪"

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

    # 维度3：异常路径建议（LLM 真实化——按用例内容定制；LLM 失败降级为通用提示）
    async def _suggest_exception_paths(self, case) -> List[Dict]:
        try:
            from app.services.ai_gateway import ai_gateway

            steps_text = "\n".join(
                f"{i+1}. [{s.get('action','')}] {s.get('target','')} → {s.get('expected','')}"
                for i, s in enumerate(case.get("steps", []))
            )
            system_prompt = "你是测试用例评审专家。只输出 JSON，不要其他文字。"
            user_prompt = f"""分析以下测试用例，找出主流程未覆盖的异常分支，给出最多 3 条补充建议。

用例名称：{case.get('name', '')}
前置条件：{case.get('precondition', '')}
步骤：
{steps_text}
预期结果：{case.get('expected_result', '')}

输出 JSON 数组，每项: {{"issue": "缺少的异常分支描述", "suggestion": "具体补充建议"}}
只输出 JSON 数组。"""

            response = await ai_gateway.chat(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": user_prompt}],
                stage="refine",
                max_tokens=1000,
            )
            data = parse_llm_json(response["content"])
            out = []
            for i, item in enumerate(data if isinstance(data, list) else []):
                out.append({
                    "id": f"S_e{i+1}", "dimension": "异常路径补充", "severity": "low",
                    "target_step": None, "issue": item.get("issue", ""),
                    "suggestion": item.get("suggestion", ""), "status": "pending",
                })
            return out
        except Exception as e:
            # LLM 不可用/格式异常 → 降级为通用提示（不阻塞精修主流程）
            logger.warning(f"LLM exception-path suggestion failed, fallback to generic: {e}")
            return [{
                "id": "S_e1", "dimension": "异常路径补充", "severity": "low",
                "target_step": None, "issue": "主流程未覆盖异常分支",
                "suggestion": "补充异常输入、超时、网络异常等路径（AI 分析暂不可用，此为通用建议）",
                "status": "pending",
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


async def llm_rewrite_steps(steps: List[Dict], suggestions: List[Dict], chat_fn=None) -> List[Dict]:
    """「断言增强」类建议的 LLM 改写：把软断言步骤改写为硬断言。

    chat_fn 可注入（测试）；默认 ai_gateway.chat。LLM 失败/输出非法 → 返回原步骤。"""
    if chat_fn is None:
        from app.services.ai_gateway import ai_gateway
        chat_fn = ai_gateway.chat

    # 只处理断言增强且有 target_step 的建议
    targets = [s for s in suggestions
               if s.get("dimension") == "断言增强" and s.get("target_step")]
    if not targets:
        return steps

    steps_text = json.dumps(steps, ensure_ascii=False)
    issues_text = json.dumps(
        [{"step": s["target_step"], "issue": s.get("issue", ""), "suggestion": s.get("suggestion", "")}
         for s in targets], ensure_ascii=False)

    system_prompt = "你是测试用例改写专家。只输出 JSON 数组，不要其他文字。"
    user_prompt = f"""改写以下测试步骤中的软断言为硬断言。

原步骤（JSON 数组）：
{steps_text}

需改写的步骤（含问题描述）：
{issues_text}

要求：
1. 只改写列出的步骤，未列出的步骤原样保留
2. action 用可执行动词（点击/填充/选择/断言），expected 必须可断言（URL/文本/数量）
3. 每项保留 step/action/target/data/expected 字段
4. 只输出改写后的完整步骤 JSON 数组"""

    try:
        resp = await chat_fn(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": user_prompt}],
            stage="refine", max_tokens=2000)
        rewritten_steps = parse_llm_json(resp["content"])
        if not isinstance(rewritten_steps, list):
            return steps
        # 按序号合并：LLM 返回的行覆盖同序号原行，其余保留
        by_seq = {r.get("step"): r for r in rewritten_steps if isinstance(r, dict) and r.get("action")}
        out = []
        for s in steps:
            r = by_seq.get(s.get("step"))
            if r and r.get("action"):
                merged = dict(s)
                merged.update({k: r[k] for k in ("action", "target", "data", "expected") if r.get(k)})
                out.append(merged)
            else:
                out.append(s)
        return out
    except Exception as e:
        logger.warning(f"LLM 步骤改写失败（不阻塞）: {e}")
        return steps
