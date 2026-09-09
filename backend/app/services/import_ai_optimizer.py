"""
导入用例 AI 优化器：自由文本候选用例 → LLM 标准化步骤四元组

失败兜底：LLM 不可用/格式漂移时返回规则版原样（ai_ok=False），不阻塞导入。
"""
import logging

from app.core.json_utils import parse_llm_json
from app.services.ai_gateway import ai_gateway

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是测试用例标准化助手。用户给出的步骤描述信息是完整的，你的任务是把每步描述【拆分】为动作/目标/数据/预期四个字段，而不是改写或缩写。

## 四字段定义与拆分规则

- action（动作）：单个动词，只能是：点击/输入/选择/勾选/打开/进入/等待/断言。描述句里无论写成"账号输入test02"还是"输入账号"，动词都归一到"输入"。
- target（目标）：动作的承受对象（控件/元素），如 浏览器地址栏/账号输入框/密码输入框/登录按钮/提交按钮/左侧菜单。描述里的"账号输入test02"目标就是"账号输入框"；"输入网址http://xxx"目标就是"浏览器地址栏"。
- data（数据）：输入的具体内容，如 test02 / Admin@17866 / http://xxx / 123456。非输入类动作为空字符串。
- expected（预期）：该步骤执行成功后的可观察结果。描述句里已写明的断言/结果直接用；没写明的按常识补全，如：
  - 输入网址xx → 进入登录页
  - 账号输入test02 → 账号输入框显示 test02
  - 密码填写Admin@17866 → 密码输入框显示为密文
  - 点击登录按钮 → 跳转到系统首页
  - 点击提交按钮 → 提示提交成功

## 拆分示例

输入描述："账号输入test02"
输出步骤：{"step":1, "action":"输入", "target":"账号输入框", "data":"test02", "expected":"账号输入框显示 test02"}

输入描述："输入网址http://dm-terminal-manage-ui.richdm.local/terminal-manage-ui/#/login"
输出步骤：{"step":1, "action":"输入", "target":"浏览器地址栏", "data":"http://dm-terminal-manage-ui.richdm.local/terminal-manage-ui/#/login", "expected":"进入登录页"}

输入描述："点击右下角的提交按钮"
输出步骤：{"step":1, "action":"点击", "target":"提交按钮", "data":"", "expected":"提交成功"}

## 约束

1. 逐步拆分，不合并、不删减步骤；保持语义不变，不臆造描述里不存在的操作
2. 确实无法确定预期时才填"待补"，能推断的一定要推断出来
3. expected_result 为整条用例最终预期结果（原样保留描述里给出的总预期）
4. priority 仅允许 P0/P1/P2/P3；用例名保持原样
5. 只返回 JSON，不要 markdown 围栏，格式：
{"name":"用例名","priority":"P1","steps":[{"step":1,"action":"输入","target":"...","data":"...","expected":"..."}],"expected_result":"..."}"""


async def optimize_case(case: dict, project_id: str) -> tuple:
    """AI 标准化单条候选用例。

    Returns:
        (optimized_case, ai_ok)：任何失败返回 (原 case, False)。
    """
    import json as _json
    try:
        user_prompt = (
            "请逐步拆分以下测试用例的每个步骤为 动作/目标/数据/预期：\n"
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
