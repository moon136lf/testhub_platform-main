"""Regression case generator: code_issue + AI fix -> platform TestCase.

Reuses #2 conventions: StepSchema shape + forbidden words. Output is a plain
dict (steps list of {step,action,target,data,expected}); caller persists into
test_case with source_issue_id association.
"""
import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 同 #2 禁用词（软断言词不进 action/expected）
# #2 无单一公共常量：case_refiner.FORBIDDEN_TAUTOLOGICAL_ASSERTIONS 是 9 词黑名单
# （多 看到/显示/观看/浏览），hallucination_detector 用实例属性。此处按计划取
# 5 词核心集，与 test_case_generator prompt 中禁用词行一致。
FORBIDDEN_WORDS = ("观察", "查看", "验证", "检查", "确认")

_PROMPT = """你是一位资深的测试架构师。请基于以下【代码问题(code_issue)】+【AI修复建议】+【代码上下文】，
生成回归测试用例。

分析要求（5 条，全部落实）：
1. 基于代码依赖（精准打击）：优先为被修改函数/类的直接调用方和下游依赖生成
2. 兼顾新旧路径：验证老功能未被改坏（防退化），非仅验证新功能
3. 数据隔离与幂等性：使用唯一标识(UUID)或临时账户，并发不冲突
4. 断言精细化：拒绝模糊断言（如"页面正常"），必须校验具体业务状态码/数据结构/元素属性
5. 异常与容错覆盖：除主流程，根据 try-catch/降级/超时生成异常注入用例

禁用词：action 与 expected 不得包含以下软断言词：{forbidden}

输出 JSON（不要 markdown 围栏，平台 TestCase 格式，强制自动化形式）：
{{
  "name": "REG-XXX_验证意图",
  "priority": "P0|P1|P2",
  "precondition": "前置条件",
  "steps": [
    {{"step": 1, "action": "navigate|click|input|select|check|assert|wait",
      "target": "目标元素", "data": "测试数据", "expected": "可断言预期(URL/文本/状态)"}}
  ],
  "expected_result": "最终可断言预期"
}}"""


class RegressionCaseGenerator:
    def __init__(self, gateway):
        self.gateway = gateway

    # allowed step verbs (spec §3.3 强制自动化形式)
    ALLOWED_ACTIONS = {"navigate", "click", "input", "select", "check", "assert", "wait"}

    def _validate_case(self, case: dict) -> None:
        """Post-LLM validation (spec §3.3: 5 rules + forbidden words live in
        prompt + VALIDATOR, prompt alone is not enforcement). Raises ValueError
        on violation (review I5)."""
        # 1. forbidden soft-assert words must not appear in name/action/expected
        name = case.get("name", "") or ""
        expected_result = case.get("expected_result", "") or ""
        steps = case.get("steps") or []
        blobs = [name, expected_result]
        for s in steps:
            if isinstance(s, dict):
                blobs.append(s.get("action", "") or "")
                blobs.append(s.get("expected", "") or "")
        for word in FORBIDDEN_WORDS:
            for b in blobs:
                if word in b:
                    raise ValueError(
                        f"forbidden word '{word}' in generated case (soft-assert term)")
        # 2. step shape + action whitelist
        for i, s in enumerate(steps, 1):
            if not isinstance(s, dict):
                raise ValueError(f"step {i} is not an object")
            action = (s.get("action", "") or "").strip().lower()
            if action not in self.ALLOWED_ACTIONS:
                raise ValueError(f"step {i} action '{action}' not in allowed verbs")
        # 3. minimal required fields
        if not name.strip():
            raise ValueError("case name is empty")
        if not steps:
            raise ValueError("case has no steps")
        if not expected_result.strip():
            raise ValueError("case expected_result is empty")

    async def generate_case(self, issue: Dict, ai_suggestion: Dict,
                            project_id: Optional[str] = None) -> dict:
        """issue: code_issue.to_dict(); ai_suggestion: issue.ai_suggestion.
        project_id forwarded to gateway.chat for ai_call_log token tracking
        (review I7 — was dropped, fixes never reached ai_call_log).
        Returns TestCase-ready dict WITHOUT source_issue_id (caller sets it)."""
        messages = [{"role": "user", "content": _PROMPT.format(
            forbidden="、".join(FORBIDDEN_WORDS),
        ) + f"""

【代码问题】{issue.get('title','')}（{issue.get('file_path','')}:{issue.get('line_no','')}，severity={issue.get('severity','')}）
【描述】{issue.get('description','')}
【问题代码】{(issue.get('example_code') or '')[:1500]}
【AI修复建议】{json.dumps(ai_suggestion or {}, ensure_ascii=False)[:1500]}"""}]

        resp = await self.gateway.chat(messages, stage="whitescan_regression_case",
                                       project_id=project_id or None)
        content = (resp or {}).get("content", "")
        try:
            case = json.loads(content)
        except (json.JSONDecodeError, AttributeError) as e:
            raise ValueError(f"regression case LLM returned non-JSON: {content[:200]}") from e

        # normalize + strip fields the caller owns
        case.pop("source_issue_id", None)
        steps = case.get("steps") or []
        for i, s in enumerate(steps, 1):
            if isinstance(s, dict):
                s.setdefault("step", i)
        case["steps"] = steps
        # spec §3.3: prompt + validator together enforce the case contract
        self._validate_case(case)
        return case

    async def _case_exists(self, project_id: str, issue_id: str) -> bool:
        """Overridden in batch to query test_case by source_issue_id. Injectable
        for tests."""
        raise NotImplementedError

    async def batch_generate(self, project_id: str, issues: List[Dict]) -> dict:
        """Incremental: skip issues that already produced a case (WHITE-05 增量).
        issues: list of issue dicts; each may carry '_case_exists' bool? No —
        caller resolves via _case_exists(project_id, issue.id)."""
        generated = skipped = failed = 0
        errors = []
        for issue in issues:
            iid = str(issue.get("id"))
            try:
                if await self._case_exists(project_id, iid):
                    skipped += 1
                    continue
                await self.generate_case(issue, issue.get("ai_suggestion") or {},
                                         project_id=project_id)
                generated += 1
            except Exception as e:
                failed += 1
                errors.append({"issue_id": iid, "error": str(e)})
        return {"generated_count": generated, "skipped_count": skipped,
                "failed_count": failed, "errors": errors}
