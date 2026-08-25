"""
Test Case Generator Service - Generate detailed test cases from test points
"""

import json
import logging
from typing import Dict

from app.services.ai_gateway import ai_gateway
from app.models.test_case import TestPoint

logger = logging.getLogger(__name__)


class TestCaseGenerator:
    """测试用例生成服务"""

    async def generate_from_point(self, point: TestPoint) -> Dict:
        """
        从测试点生成详细用例

        Args:
            point: TestPoint对象（包含page_name, name, type_label, description, id）

        Returns:
            用例数据Dict，包含: name, priority, precondition, steps, expected_result, point_id

        Raises:
            ValueError: 当用例生成失败或AI返回格式错误时
        """
        try:
            logger.info(f"Generating test case for point: {point.name}")

            # Build prompt
            system_prompt = """你是一个专业的测试用例编写专家。请根据测试点生成详细的测试用例。

要求：
1. 用例步骤必须详细、可执行、面向UI自动化
2. 每个步骤包含：action（操作类型）、target（操作目标元素）、data（操作数据）、expected（该步预期结果）
3. action 可选值：navigate, click, input, select, check, assert, wait（禁止使用 verify）
4. 禁用词：观察、查看、验证、检查、确认——不得出现在 action 或 expected 中；动作必须用可执行动词：点击、填充、选择、断言
5. target 应该是具体的UI元素描述（如"登录按钮"、"用户名输入框"）
6. expected_result 是最终预期结果（必须可断言：URL/文本/状态），不得为"系统正常处理""以实际为准"等模糊表述
7. priority 是 P0/P1/P2

返回JSON格式：
{
  "name": "用例名称",
  "priority": "P1",
  "precondition": "前置条件",
  "steps": [
    {"action": "navigate", "target": "登录页面", "data": "https://example.com/login", "expected": "跳转到登录页"},
    {"action": "input", "target": "用户名输入框", "data": "testuser", "expected": "输入框显示 testuser"},
    {"action": "click", "target": "登录按钮", "data": "", "expected": "跳转到首页"}
  ],
  "expected_result": "登录成功后跳转到首页"
}

只返回JSON，不要其他说明文字。"""

            user_prompt = f"""请为以下测试点生成用例：

页面：{point.page_name}
测试点名称：{point.name}
类型：{point.type_label}
描述：{point.description or "无"}

生成面向UI自动化的详细测试用例。"""

            # Call AI gateway
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            logger.info("Calling AI gateway with provider=glm-4")
            response = await ai_gateway.chat(
                messages, provider="glm-4",
                project_id=str(point.project_id) if hasattr(point, "project_id") and point.project_id else None,
                stage="generate_case",
            )

            # Parse JSON response
            content = response["content"]

            try:
                case_data = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse failed: {e}, content: {content[:200]}")
                raise Exception("用例生成失败：AI返回格式错误") from e

            # Validate JSON structure
            required_keys = ["name", "priority", "steps", "expected_result"]
            missing_keys = [key for key in required_keys if key not in case_data]
            if missing_keys:
                raise Exception(f"用例生成失败：AI返回缺少必需字段 {missing_keys}")

            # Add point_id to case data
            case_data["point_id"] = str(point.id)

            logger.info(f"Test case generated successfully for point: {point.name}")
            return case_data

        except Exception as e:
            logger.error(f"Test case generation failed: {e}")
            raise
