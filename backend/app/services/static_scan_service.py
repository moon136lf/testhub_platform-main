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
from uuid import UUID as _UUID

from sqlalchemy import select as _select, update as _update, func as _func

from app.models.element import PageRepository, ElementRepository

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
_ATTR_ID_RE = re.compile(r"(?<![\w-])(?::)?id\s*=\s*[\"']([^\"']+)[\"']")
_ATTR_HREF_RE = re.compile(r"href\s*=\s*[\"']([^\"']+)[\"']")
_ATTR_NAME_RE = re.compile(r"(?<!\w)name\s*=\s*[\"']([^\"']+)[\"']")
_ATTR_TESTID_RE = re.compile(r"data-testid\s*=\s*[\"']([^\"']+)[\"']")
_TEMPLATE_RE = re.compile(r"<template>(.*)</template>", re.DOTALL | re.IGNORECASE)
# 插值/静态文本: 从开标签结束处 match——先跳过若干完整嵌套子元素（<x>…</x>），
# 再取紧邻的第一个文本节点，且其后第一个标签必须是与当前标签同名的闭合标签
# （保证文本归属当前元素，不误抓空标签的兄弟文本/嵌套子元素的文本）
_TEXT_RE = re.compile(
    r"\s*(?:<[a-zA-Z][^<>]*>.*?</[a-zA-Z][\w-]*>\s*)*([^<>{}]{1,50}?)\s*</([a-zA-Z][\w-]*)>",
    re.DOTALL,
)

SNIPPET_MAX = 4000

import json as _json

PROMPT_TEMPLATE = """你是前端测试专家。以下是一个 Vue 组件的 template 片段和其中可交互元素清单。
为每个元素生成 Playwright 可用的定位策略链。

【可用策略类型】id, css, xpath, placeholder, text, role, anchor, sibling-label。
anchor: 唯一 id/data-testid 祖先 + 1-2 层相对路径，如 "[data-testid='save-btn'] > button"。
sibling-label: XPath 兄弟表单定位，如 "//label[contains(.,'用户名')]/following-sibling::input"（撇号用双引号字面量，XPath 1.0 无转义）。

【要求】
1. 输出纯 JSON 数组（无 markdown 围栏），每项 {{"index": <元素序号>, "strategies": [{{"type": "...", "value": "...", "priority": 1}}]}}
2. index 对应元素清单顺序（从 0 开始）
3. 每元素 1-4 条策略，稳定策略优先（id/data-testid > anchor > sibling-label > css > text）
4. v-model 通常是表单字段名，label 文本常在 el-form-item label 属性——参考片段上下文推断
5. 不得虚构片段中不存在的属性

【组件】{component_name}（文件 {file_path}）

【template 片段】
{snippet}

【元素清单】
{element_list}
"""


class StaticScanService:
    """源码静态提取 + AI 定位器生成 + 入库"""

    def __init__(self, gateway=None):
        self.gateway = gateway

    # ---------- AI 生成 ----------

    @staticmethod
    def build_prompt(comp: Dict[str, Any]) -> str:
        lines = []
        for i, e in enumerate(comp["elements"]):
            attrs = {k: e.get(k) for k in ("text", "v_model", "placeholder", "id", "name", "data_testid") if e.get(k)}
            lines.append(f"{i}. <{e['tag']}> {attrs}")
        return PROMPT_TEMPLATE.format(
            component_name=comp["component_name"],
            file_path=comp["file_path"],
            snippet=comp["template_snippet"],
            element_list="\n".join(lines),
        )

    @staticmethod
    def compute_component_hash(comp: Dict[str, Any]) -> str:
        """组件内容 hash = snippet 摘要 + 完整提取元素清单规范化摘要。

        snippet 截断到 SNIPPET_MAX 后，截断点之外的元素属性变化仅体现在
        elements 列表——把元素关键字段一并纳入 hash 输入，避免复用过期定位器。
        """
        canonical_elements = []
        for e in comp.get("elements") or []:
            canonical_elements.append({
                k: e.get(k)
                for k in ("tag", "id", "name", "data_testid", "v_model", "text", "pos")
            })
        digest_input = _json.dumps(
            {
                "snippet": comp.get("template_snippet") or "",
                "elements": canonical_elements,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha1(digest_input.encode("utf-8")).hexdigest()

    @staticmethod
    def parse_ai_output(content: str):
        """解析 AI 输出：裸 JSON / ```json 围栏 / 前导文字+围栏或裸 JSON。失败返回 None。"""
        if not content:
            return None
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = _json.loads(text)
        except _json.JSONDecodeError:
            # 前导文字（"好的：```json..."）兜底：提取首个 [ 到末个 ]（或 { 到 }）再试
            data = None
            for open_c, close_c in (("[", "]"), ("{", "}")):
                start, end = text.find(open_c), text.rfind(close_c)
                if start != -1 and end > start:
                    try:
                        data = _json.loads(text[start:end + 1])
                        break
                    except _json.JSONDecodeError:
                        continue
            if data is None:
                return None
        return data if isinstance(data, list) else None

    async def generate_component(self, comp: Dict[str, Any]) -> Dict[str, Any]:
        """调 glm 生成组件内所有元素的定位器。失败重试 1 次，仍失败标记 ai_failed。"""
        prompt = self.build_prompt(comp)
        content = None
        for attempt in (1, 2):
            try:
                resp = await self.gateway.chat(
                    [{"role": "user", "content": prompt}],
                    provider="glm-2.5",  # provider key 历史遗留，实际模型 glm-5.2
                    stage="static_scan_locator",
                )
                data = self.parse_ai_output(resp.get("content", ""))
                if data is not None:
                    content = data
                    break
            except Exception as e:
                logger.warning(f"AI generate attempt {attempt} failed | component={comp['component_name']}: {e}")
        if content is None:
            comp["ai_failed"] = True
            return comp
        by_index = {item.get("index"): item.get("strategies") for item in content if isinstance(item, dict)}
        for i, e in enumerate(comp["elements"]):
            strategies = by_index.get(i)
            if isinstance(strategies, list) and strategies:
                e["locator_strategies"] = {"strategies": strategies}
        comp["ai_failed"] = False
        return comp

    # ---------- hash 增量 ----------

    @staticmethod
    def decide_reuse(comp: Dict[str, Any], prior: Dict[str, Dict]) -> Dict[str, Any] | None:
        """hash 未变 → 复用旧定位器（写回 elements），返回 reused 决策；否则 None。

        prior: {file_path: {content_hash, strategies_by_index: {index: {"strategies": [...]}}}}
        """
        record = prior.get(comp["file_path"])
        if not record or record.get("content_hash") != comp["content_hash"]:
            return None
        prior_strategies = record.get("strategies_by_index") or {}
        # 元素数量或位置变化则不复用（索引错位风险）
        if len(prior_strategies) != len(comp["elements"]) or not comp["elements"]:
            return None
        for i, e in enumerate(comp["elements"]):
            s = prior_strategies.get(i)
            if not s:
                return None
            e["locator_strategies"] = {"strategies": s["strategies"]}
        return {"reused": True}

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
            # 自闭合标签（<input .../>）无子文本；否则取紧随其后的文本，
            # 且文本后第一个闭合标签须与当前标签同名（防止兄弟/子元素文本误归属）
            text = None
            if not attrs.rstrip().endswith("/"):
                tm = _TEXT_RE.match(template, m.end())
                if tm and tm.group(2).lower() == tag:
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
            comp = {
                "file_path": rel,
                "component_name": component_name,
                "template_snippet": snippet,
                "elements": self._extract_elements(template),
            }
            comp["content_hash"] = self.compute_component_hash(comp)
            comps.append(comp)
        return comps

    # ---------- 入库 ----------

    @staticmethod
    def build_element_id(file_path: str, elem: Dict[str, Any], pos: int = 0) -> str:
        """源码场景元素标识：文件短名 + 优先 id/testid/name/text，兜底 tag+行号。"""
        stem = os.path.splitext(os.path.basename(file_path))[0].lower()
        for key in ("id", "data_testid", "name", "text"):
            v = elem.get(key)
            if v and str(v).strip():
                return f"{stem}_{str(v).strip()[:80]}"[:100]
        return f"{stem}_{elem.get('tag', 'elem')}_{pos}"[:100]

    async def _get_or_create_page(self, db, project_id: str, comp: Dict[str, Any],
                                  route_path: str | None) -> str:
        """组件 → 页面树节点。page_url 用路由路径（有路由表）或文件相对路径，幂等。"""
        page_url = route_path or f"static:{comp['file_path']}"
        existing = await db.execute(
            _select(PageRepository).where(
                PageRepository.project_id == _UUID(project_id),
                PageRepository.page_url == page_url,
            )
        )
        page = existing.scalar_one_or_none()
        if page:
            return page.id
        page = PageRepository(
            project_id=_UUID(project_id),
            page_name=comp["component_name"][:100],
            page_url=page_url[:500],
            screenshot_url=None,
            element_count=0,
            created_by="static_scan",
        )
        db.add(page)
        await db.flush()  # 拿 id，不 commit（由 import_component 统一 commit）
        return page.id

    async def import_component(self, db, project_id: str, comp: Dict[str, Any],
                               route_path: str | None) -> tuple:
        """单组件入库。返回 (page_id, imported, skipped)。ai_failed 组件跳过不入库。"""
        if comp.get("ai_failed") or not comp.get("elements"):
            return None, 0, 0
        page_id = await self._get_or_create_page(db, project_id, comp, route_path)

        # 已有元素 element_id → locator_strategies（I-1: 重导入 diff 刷新定位器）
        existing = await db.execute(
            _select(ElementRepository.element_id, ElementRepository.locator_strategies).where(
                ElementRepository.page_id == page_id)
        )
        existing_map = {row[0]: row[1] for row in existing.all()}

        imported, skipped, updated = 0, 0, 0
        seen = set()
        type_counters: Dict[str, int] = {}
        for i, e in enumerate(comp["elements"]):
            if "locator_strategies" not in e:
                skipped += 1  # AI 未产出该元素的策略
                continue
            element_id = self.build_element_id(comp["file_path"], e, pos=e.get("pos", i))
            if element_id in seen:
                skipped += 1
                continue
            seen.add(element_id)

            if element_id in existing_map:
                # I-1: 定位器变化则刷新，相同则 skip
                if existing_map[element_id] != e["locator_strategies"]:
                    await db.execute(
                        _update(ElementRepository)
                        .where(ElementRepository.page_id == page_id,
                               ElementRepository.element_id == element_id)
                        .values(locator_strategies=e["locator_strategies"],
                                updated_at=_func.now())
                    )
                    updated += 1
                else:
                    skipped += 1
                continue

            text = (e.get("text") or "").strip()
            element_text = text[:200] if text else None
            elem_type = "link" if e["tag"] == "a" else ("input" if e["tag"] in ("el-input", "input", "textarea", "el-textarea") else "button")
            type_counters[elem_type] = type_counters.get(elem_type, 0) + 1

            name = (e.get("text") or "").strip() or f"{elem_type}{type_counters[elem_type]}"

            db.add(ElementRepository(
                page_id=page_id,
                project_id=_UUID(project_id),
                element_id=element_id,
                element_name=name[:100],
                element_type=elem_type,
                element_text=element_text,
                locator_strategies=e["locator_strategies"],
                semantic_info={
                    "type": elem_type,
                    "text": element_text,
                    "placeholder": e.get("placeholder"),
                    "context": {"source_file": comp["file_path"], "line": e.get("pos")},
                    "coords": {"x": 0, "y": 0, "width": 0, "height": 0},
                },
                attributes={k: v for k, v in {
                    "id": e.get("id"), "name": e.get("name"),
                    "placeholder": e.get("placeholder"), "data-testid": e.get("data_testid"),
                }.items() if v} or None,
                status="active",
                confidence=5,
                source="static_scan",
                created_by="system",
            ))
            imported += 1

        # I-2: element_count 回填/累加（本次新建元素数，更新的不重复计数）
        if imported:
            await db.execute(
                _update(PageRepository)
                .where(PageRepository.id == page_id)
                .values(element_count=_func.coalesce(PageRepository.element_count, 0) + imported)
            )
        await db.commit()
        return page_id, imported, skipped
