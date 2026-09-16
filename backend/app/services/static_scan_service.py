"""StaticScanService — 源码定位器链路（缺口3）。

extract: 遍历 .vue，regex 提取 <template> 可交互元素 + 内容 hash。
generate: glm-5.2 逐组件生成 locator_strategies（hash 未变复用）。
import: source=static_scan 入元素库挂页面树。
"""
import hashlib
import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# 跳过目录（对齐 CodeStructureAnalyzer）
SKIP_DIRS = {"node_modules", "dist", "build", ".git", "__pycache__", "venv", ".venv", ".claude", "worktrees"}

# 可交互标签（原生 + Element Plus 常用）
_INTERACTIVE_TAGS = (
    "input", "button", "select", "textarea", "a",
    "el-button", "el-input", "el-select", "el-textarea", "el-link",
    "el-checkbox", "el-radio", "el-switch", "el-upload", "el-date-picker",
    "el-cascader", "el-autocomplete", "el-input-number", "el-slider",
)

# 标签开头 → 交互判定（el-xxx 前缀下 _INTERACTIVE_TAGS 精确匹配）
_TAG_OPEN_RE = re.compile(r"<([a-zA-Z][\w-]*)\b([^>]*)>")
_ATTR_V_MODEL_RE = re.compile(r"v-model(?:\.\w+)*\s*=\s*[\"']([^\"']+)[\"']")
_ATTR_PLACEHOLDER_RE = re.compile(r"placeholder\s*=\s*[\"']([^\"']+)[\"']")
_ATTR_ID_RE = re.compile(r"(?::)?id\s*=\s*[\"']([^\"']+)[\"']")
_ATTR_HREF_RE = re.compile(r"href\s*=\s*[\"']([^\"']+)[\"']")
_ATTR_NAME_RE = re.compile(r"(?<!\w)name\s*=\s*[\"']([^\"']+)[\"']")
_ATTR_TESTID_RE = re.compile(r"data-testid\s*=\s*[\"']([^\"']+)[\"']")
_TEMPLATE_RE = re.compile(r"<template>(.*)</template>", re.DOTALL | re.IGNORECASE)
# 插值/静态文本: 紧跟开标签之后的标签间可见文本
_TEXT_RE = re.compile(r"\s*([^<>{}]{1,50}?)\s*<")

SNIPPET_MAX = 4000


class StaticScanService:
    """源码静态提取 + AI 定位器生成 + 入库"""

    # ---------- 提取 ----------

    @staticmethod
    def _walk_vue(repo_path: str):
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith(".vue"):
                    yield os.path.join(root, f)

    @classmethod
    def _template_of(cls, content: str) -> str:
        m = _TEMPLATE_RE.search(content)
        return m.group(1) if m else ""

    @classmethod
    def _extract_elements(cls, template: str) -> List[Dict[str, Any]]:
        elements: List[Dict[str, Any]] = []
        for m in _TAG_OPEN_RE.finditer(template):
            tag, attrs = m.group(1).lower(), m.group(2)
            if tag not in _INTERACTIVE_TAGS:
                continue
            # 自闭合标签（<input .../>）无子文本；否则取紧随其后的文本
            text = None
            tm = _TEXT_RE.search(template, m.end())
            if tm and not attrs.rstrip().endswith("/"):
                text = tm.group(1).strip() or None
            el = {
                "tag": tag,
                "text": text,
                "v_model": _ATTR_V_MODEL_RE.search(attrs),
                "placeholder": _ATTR_PLACEHOLDER_RE.search(attrs),
                "id": _ATTR_ID_RE.search(attrs),
                "href": _ATTR_HREF_RE.search(attrs),
                "name": _ATTR_NAME_RE.search(attrs),
                "data_testid": _ATTR_TESTID_RE.search(attrs),
                "pos": template[:m.start()].count("\n") + 1,  # 行号，供元素命名与调试
            }
            # Match 对象不能跨调用存活 → 落地为字符串
            for k in ("v_model", "placeholder", "id", "href", "name", "data_testid"):
                el[k] = el[k].group(1) if el[k] else None
            elements.append(el)
        return elements

    def extract_components(self, repo_path: str) -> List[Dict[str, Any]]:
        """产物: [{file_path(相对路径,正斜杠), component_name, template_snippet, content_hash, elements}]"""
        comps: List[Dict[str, Any]] = []
        for abs_path in self._walk_vue(repo_path):
            rel = os.path.relpath(abs_path, repo_path).replace("\\", "/")
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError as e:
                logger.warning(f"read failed, skip | file={rel}: {e}")
                continue
            template = self._template_of(content)
            if not template:
                continue
            component_name = os.path.splitext(os.path.basename(abs_path))[0]
            snippet = template.strip()[:SNIPPET_MAX]
            comps.append({
                "file_path": rel,
                "component_name": component_name,
                "template_snippet": snippet,
                "content_hash": hashlib.sha1(snippet.encode("utf-8")).hexdigest(),
                "elements": self._extract_elements(template),
            })
        return comps
