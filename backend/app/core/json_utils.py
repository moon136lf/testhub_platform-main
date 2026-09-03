"""
LLM 输出 JSON 解析工具

模型（如 GLM）即使提示词要求「只返回 JSON」，也常把 JSON 包在 ```json ... ```
markdown 围栏里返回。统一在 parse 前剥掉围栏，避免不必要的解析失败。
"""

import json
import re


def strip_json_fences(content: str) -> str:
    """剥掉 markdown 代码围栏（```json ... ``` / ``` ... ```）"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^`{3}(?:json)?\s*", "", text)
        text = re.sub(r"\s*`{3}\s*$", "", text)
    return text.strip()


def parse_llm_json(content: str):
    """剥围栏后 json.loads；失败抛 JSONDecodeError"""
    return json.loads(strip_json_fences(content))
