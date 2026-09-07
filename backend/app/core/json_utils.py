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
    """剥围栏后 json.loads；失败再尝试取首个平衡的 {...} 块（模型偶尔在
    JSON 后附带说明文字 → 'Extra data' 错误），仍失败抛 JSONDecodeError"""
    text = strip_json_fences(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 取第一个 '{' 到与其配对的 '}'（ respecting 字符串/转义）
        start = text.find("{")
        if start == -1:
            raise
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
        raise
