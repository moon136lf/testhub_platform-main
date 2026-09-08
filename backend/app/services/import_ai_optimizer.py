"""
导入用例 AI 优化器：自由文本候选用例 → LLM 标准化步骤四元组

失败兜底：LLM 不可用/格式漂移时返回规则版原样（ai_ok=False），不阻塞导入。
"""
import logging

from app.core.json_utils import parse_llm_json
from app.services.ai_gateway import ai_gateway

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是测试用例标准化助手。将自由文本测试步骤改写为标准四元组步骤。

要求：
1. 每步输出 {"step":序号, "action":动作(以动词开头，如 点击/输入/选择/断言), "target":操作对象, "data":输入数据, "expected":该步骤预期结果}
2. 保持语义不变，不新增不存在的步骤；缺失的预期可填"待补"
3. expected_result 为整条用例最终预期结果
4. priority 仅允许 P0/P1/P2/P3
5. 只返回 JSON，不要 markdown 围栏，格式：
{"name":"用例名","priority":"P1","steps":[...],"expected_result":"..."}"""


async def optimize_case(case: dict, project_id: str) -> tuple:
    """AI 标准化单条候选用例。

    Returns:
        (optimized_case, ai_ok)：任何失败返回 (原 case, False)。
    """
    import json as _json
    try:
        user_prompt = (
            "请标准化以下测试用例：\n"
            + _json.dumps(case, ensure_ascii=False)
        )
        response = await ai_gateway.chat(
            [{"role": "system", "content": _SYSTEM_PROMPT},
             {"role": "user", "content": user_prompt}],
            project_id=project_id,
            stage="import_refine",
            max_tokens=1500,
        )
        data = parse_llm_json(response["content"])
        if not isinstance(data, dict):
            raise ValueError("AI 返回不是对象")

        steps = data.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("AI 返回缺少 steps")

        normalized_steps = []
        for i, s in enumerate(steps, 1):
            if not isinstance(s, dict):
                raise ValueError("steps 元素格式错误")
            action = str(s.get("action") or "").strip()
            expected = str(s.get("expected") or "待补").strip() or "待补"
            if not action:
                raise ValueError("步骤缺少 action")
            normalized_steps.append({
                "step": i, "action": action[:2000],
                "target": (str(s.get("target") or "").strip() or None),
                "data": (str(s.get("data") or "").strip() or None),
                "expected": expected[:2000],
            })

        optimized = dict(case)
        if data.get("name"):
            optimized["name"] = str(data["name"]).strip()[:100] or case.get("name", "")
        if str(data.get("priority") or "") in ("P0", "P1", "P2", "P3"):
            optimized["priority"] = data["priority"]
        optimized["steps"] = normalized_steps
        optimized["expected_result"] = (str(data.get("expected_result") or "").strip()
                                        or case.get("expected_result", "待补"))[:200]
        return optimized, True
    except Exception as e:
        logger.warning(f"AI optimize case failed, fallback to rule version: {e}")
        return case, False
