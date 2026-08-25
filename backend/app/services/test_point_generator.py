"""
Test Point Generator Service - AI-based test point extraction from PRD documents
"""

import json
import logging
from typing import List, Dict, Optional

from app.services.ai_gateway import ai_gateway

logger = logging.getLogger(__name__)


class TestPointGenerator:
    """测试点生成服务"""

    def _build_system_prompt(self, rules: List[str]) -> str:
        """
        构建系统 prompt

        Args:
            rules: 测试规则列表

        Returns:
            系统 prompt 字符串
        """
        rules_text = "\n".join(f"- {rule}" for rule in rules)

        return f"""你是一个专业的测试工程师。请根据以下测试规则从PRD文档中识别测试点：

{rules_text}

请以JSON格式返回测试点，格式如下：
{{
  "pages": [
    {{
      "page_name": "页面名称",
      "test_points": [
        {{
          "name": "测试点名称",
          "type_label": "正常流程",
          "description": "测试点描述"
        }}
      ]
    }}
  ]
}}

注意：
1. 每个测试点必须清晰、可执行
2. type_label 只能是：正常流程、异常流程、边界值、等价类、场景法
3. 按页面分组输出
4. 只返回JSON，不要其他说明文字
"""

    async def generate(
        self,
        doc_content: str,
        rules: List[str],
        knowledge_context: str,
        project_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        从PRD文档中AI识别测试点

        Args:
            doc_content: PRD文档内容
            rules: 测试规则Prompt列表
            knowledge_context: 知识库上下文
            project_id: 项目ID，传入则记录 token 用量到 ai_call_log（W10 埋点）

        Returns:
            测试点列表，每个元素包含: page_name, name, type_label, description

        Raises:
            ValueError: 当AI返回格式不正确时
        """
        try:
            logger.info("Starting test point generation")

            # Limit content length
            limited_doc = doc_content[:5000]
            limited_knowledge = knowledge_context[:2000]

            # Build prompts
            system_prompt = self._build_system_prompt(rules)
            user_prompt = f"""PRD文档内容：
{limited_doc}

知识库参考：
{limited_knowledge}

请识别测试点并按JSON格式返回。"""

            # Call AI gateway
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            logger.info("Calling AI gateway with provider=glm-4")
            response = await ai_gateway.chat(
                messages, provider="glm-4",
                project_id=str(project_id) if project_id else None,
                stage="identify_point",
            )

            # Parse JSON response
            content = response["content"]

            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse failed: {e}, content: {content[:200]}")
                raise Exception("AI返回格式不正确") from e

            # Validate JSON structure
            if "pages" not in data:
                raise Exception("AI返回格式不正确：缺少pages字段")

            # Extract and flatten test points
            test_points = []
            pages = data.get("pages", [])

            for page in pages:
                page_name = page.get("page_name", "")
                points = page.get("test_points", [])

                for point in points:
                    test_points.append({
                        "page_name": page_name,
                        "name": point.get("name", ""),
                        "type_label": point.get("type_label", "正常流程"),
                        "description": point.get("description", "")
                    })

            logger.info(f"Test point generation completed, total points: {len(test_points)}")
            return test_points

        except Exception as e:
            logger.error(f"Test point generation failed: {e}")
            raise
