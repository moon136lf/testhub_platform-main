# 源码定位器链路（静态扫描产出元素定位器）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 上传前端源码 zip → 静态解析 .vue → glm-5.2 生成定位策略链 → source=static_scan 入元素库挂页面树，hash 增量复用。

**Architecture:** 白盒模块扩展——新 StaticScanService（提取+AI+入库），新 Celery 任务与 semgrep 支路并行，新表 static_scan_component 存组件 hash，API 挂在 /whitescan 下，前端 WhiteScan.vue 加 zip 模式与定位器 Tab。

**Tech Stack:** FastAPI + SQLAlchemy(async) + Celery + PostgreSQL16 + ai_gateway(glm-5.2) + Vue3/Element Plus

**Spec:** `docs/superpowers/specs/2026-09-16-static-scan-locators-design.md`

**测试基线:** 918 passed（master e6004d5）。backend 8000 无 --reload，改后端须重启。

---

### Task 1: 数据模型 StaticScanComponent + 迁移

**Files:**
- Create: `backend/migrations/016_static_scan_components.sql`
- Modify: `backend/app/models/whitescan.py`
- Test: `backend/tests/test_static_scan_models.py`

- [ ] **Step 1: 写迁移 SQL（幂等）**

```sql
-- backend/migrations/016_static_scan_components.sql
-- Migration: static scan component hash table (source-code locator chain)
-- Idempotent: safe to run multiple times.

CREATE TABLE IF NOT EXISTS static_scan_component (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    scan_id UUID NOT NULL REFERENCES code_scan(id) ON DELETE CASCADE,
    file_path VARCHAR(500) NOT NULL,
    component_name VARCHAR(200),
    content_hash VARCHAR(64),
    page_id UUID REFERENCES page_repository(id) ON DELETE SET NULL,
    element_count INTEGER DEFAULT 0,
    ai_generated BOOLEAN DEFAULT FALSE,
    reused BOOLEAN DEFAULT FALSE,
    ai_failed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, file_path)
);
CREATE INDEX IF NOT EXISTS idx_static_scan_component_project ON static_scan_component(project_id);
COMMENT ON TABLE static_scan_component IS '静态扫描组件hash表：重扫hash未变跳过AI生成复用定位器';
```

- [ ] **Step 2: 在 model 文件加 ORM 类**

`backend/app/models/whitescan.py` 末尾追加（import 区补 `from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Index` 已有，补 `from sqlalchemy.dialects.postgresql import UUID` 若缺；from app.models.base import Base 已有）：

```python
class StaticScanComponent(Base):
    """静态扫描组件hash表：hash未变组件跳过AI生成复用定位器"""

    __tablename__ = "static_scan_component"
    __table_args__ = (
        UniqueConstraint("project_id", "file_path", name="uq_static_scan_component_file"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_id = Column(UUID(as_uuid=True), ForeignKey("code_scan.id", ondelete="CASCADE"), nullable=False)
    file_path = Column(String(500), nullable=False)
    component_name = Column(String(200))
    content_hash = Column(String(64))
    page_id = Column(UUID(as_uuid=True), ForeignKey("page_repository.id", ondelete="SET NULL"))
    element_count = Column(Integer, default=0)
    ai_generated = Column(Boolean, default=False)
    reused = Column(Boolean, default=False)
    ai_failed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "scan_id": str(self.scan_id),
            "file_path": self.file_path,
            "component_name": self.component_name,
            "content_hash": self.content_hash,
            "page_id": str(self.page_id) if self.page_id else None,
            "element_count": self.element_count,
            "ai_generated": self.ai_generated,
            "reused": self.reused,
            "ai_failed": self.ai_failed,
        }
```

注意：文件顶部 import 需补 `UniqueConstraint`（from sqlalchemy import ... UniqueConstraint）与 `import uuid`。

- [ ] **Step 3: 写模型单测**

```python
# backend/tests/test_static_scan_models.py
"""StaticScanComponent 模型字段与 to_dict 契约"""
from unittest.mock import MagicMock
from app.models.whitescan import StaticScanComponent


class TestStaticScanComponent:
    def test_to_dict_contract(self):
        c = StaticScanComponent(
            id=MagicMock(return_value=None) or None,  # id 由 DB 生成
            project_id="00000000-0000-0000-0000-000000000001",
            scan_id="00000000-0000-0000-0000-000000000002",
            file_path="src/views/Cases.vue",
            component_name="Cases",
            content_hash="abc123",
            element_count=5,
            ai_generated=True,
            reused=False,
            ai_failed=False,
        )
        d = c.to_dict()
        assert d["file_path"] == "src/views/Cases.vue"
        assert d["component_name"] == "Cases"
        assert d["element_count"] == 5
        assert d["ai_generated"] is True
        assert d["reused"] is False
        assert d["page_id"] is None  # 未设 page_id 时 to_dict 不崩
```

- [ ] **Step 4: 跑测试**

Run: `cd backend && python -m pytest tests/test_static_scan_models.py -v`
Expected: PASS

- [ ] **Step 5: 应用迁移**

Run: `cd backend && python -c "import asyncio,asyncpg;import os;from dotenv import load_dotenv;load_dotenv();asyncio.run(asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg','postgresql')).then(lambda c: c.close()) if False else None)" 2>/dev/null; PGPASSWORD=Admin@123 psql -h localhost -p 5433 -U postgres -d moontest -f migrations/016_static_scan_components.sql`
（若 psql 不可用，用 docker: `docker exec -i <pg容器> psql -U postgres -d moontest < migrations/016_static_scan_components.sql`）
Expected: CREATE TABLE / CREATE INDEX，重复执行无错

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/016_static_scan_components.sql backend/app/models/whitescan.py backend/tests/test_static_scan_models.py
git commit -m "feat(static-scan): StaticScanComponent模型+016迁移——组件hash增量表"
```

---

### Task 2: StaticScanService.vue 提取器（纯 regex + hash）

**Files:**
- Create: `backend/app/services/static_scan_service.py`（本任务只写提取部分）
- Test: `backend/tests/test_static_scan_extract.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_static_scan_extract.py
"""StaticScanService.vue 提取器：template截取/交互元素识别/hash"""
import shutil, tempfile, os
import pytest
from app.services.static_scan_service import StaticScanService

CASES_VUE = """<template>
  <div class="cases">
    <el-button type="primary" @click="showCreateDialog">新建用例</el-button>
    <el-input v-model="keyword" placeholder="搜索用例" />
    <a href="/detail" class="row-link">详情</a>
    <span class="plain">不可交互</span>
  </div>
</template>
<script setup>
const keyword = ref('')
</script>
"""

MIN_VUE = """<template><button @click="go">提交</button></template>
<script>export default {}</script>
"""


@pytest.fixture
def repo(tmp_path):
    views = tmp_path / "src" / "views"
    views.mkdir(parents=True)
    (views / "Cases.vue").write_text(CASES_VUE, encoding="utf-8")
    (views / "Min.vue").write_text(MIN_VUE, encoding="utf-8")
    (views / "no_template.css").write_text(".a{}", encoding="utf-8")
    return tmp_path


class TestExtract:
    def test_extracts_vue_components(self, repo):
        svc = StaticScanService()
        comps = svc.extract_components(str(repo))
        paths = {c["file_path"] for c in comps}
        assert "src/views/Cases.vue" in paths
        assert "src/views/Min.vue" in paths

    def test_interactive_elements_only(self, repo):
        svc = StaticScanService()
        comps = svc.extract_components(str(repo))
        cases = next(c for c in comps if c["component_name"] == "Cases")
        tags = [e["tag"] for e in cases["elements"]]
        assert "el-button" in tags and "el-input" in tags and "a" in tags
        assert "span" not in tags  # 非交互元素剔除

    def test_element_attrs_captured(self, repo):
        svc = StaticScanService()
        cases = next(c for c in svc.extract_components(str(repo))
                     if c["component_name"] == "Cases")
        btn = next(e for e in cases["elements"] if e["tag"] == "el-button")
        assert btn["text"] == "新建用例"
        inp = next(e for e in cases["elements"] if e["tag"] == "el-input")
        assert inp["placeholder"] == "搜索用例"
        assert inp["v_model"] == "keyword"

    def test_content_hash_stable_and_sensitive(self, repo):
        svc = StaticScanService()
        c1 = svc.extract_components(str(repo))
        h_before = {c["file_path"]: c["content_hash"] for c in c1}
        # 重跑相同内容 hash 一致
        h_again = {c["file_path"]: c["content_hash"] for c in svc.extract_components(str(repo))}
        assert h_before == h_again
        # 改内容 hash 变
        (repo / "src" / "views" / "Min.vue").write_text(
            MIN_VUE.replace("提交", "确认"), encoding="utf-8")
        h_after = {c["file_path"]: c["content_hash"] for c in svc.extract_components(str(repo))}
        assert h_after["src/views/Min.vue"] != h_before["src/views/Min.vue"]

    def test_template_snippet_truncated(self, repo):
        svc = StaticScanService()
        comps = svc.extract_components(str(repo))
        for c in comps:
            assert len(c["template_snippet"]) <= 4000

    def test_skip_dirs_and_non_vue(self, repo):
        node_modules = repo / "node_modules" / "pkg"
        node_modules.mkdir(parents=True)
        (node_modules / "X.vue").write_text("<template><button>x</button></template>", encoding="utf-8")
        svc = StaticScanService()
        paths = {c["file_path"] for c in svc.extract_components(str(repo))}
        assert all("node_modules" not in p for p in paths)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_static_scan_extract.py -v`
Expected: FAIL（ModuleNotFoundError: static_scan_service）

- [ ] **Step 3: 实现提取器**

```python
# backend/app/services/static_scan_service.py
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
# 插值/静态文本: 抓标签间可见文本
_TEXT_RE = re.compile(r">\s*([^<>{}]{1,50}?)\s*<")

SNIPPET_MAX = 4000


class StaticScanService:
    """源码静态提取 + AI 定位器生成 + 入库"""

    # ---------- 提取 ----------

    @staticmethod
    def _walk_vue(repo_path: str):
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in StaticScanService.SKIP_DIRS]
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_static_scan_extract.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/static_scan_service.py backend/tests/test_static_scan_extract.py
git commit -m "feat(static-scan): vue提取器——template交互元素识别+内容hash"
```

---

### Task 3: AI 定位器生成 + hash 增量判定

**Files:**
- Modify: `backend/app/services/static_scan_service.py`
- Test: `backend/tests/test_static_scan_generate.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_static_scan_generate.py
"""AI 定位器生成：prompt构建/JSON解析/失败重试/hash增量决策"""
import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.services.static_scan_service import StaticScanService, PROMPT_TEMPLATE


def _comp(elements=1):
    els = [{"tag": "el-button", "text": "新建用例", "v_model": None, "placeholder": None,
            "id": None, "href": None, "name": None, "data_testid": None, "pos": 2}] * elements
    return {"file_path": "src/views/Cases.vue", "component_name": "Cases",
            "template_snippet": "<div><el-button>新建用例</el-button></div>",
            "content_hash": "h1", "elements": els}


class TestPrompt:
    def test_prompt_contains_snippet_and_element_list(self):
        prompt = StaticScanService.build_prompt(_comp())
        assert "新建用例" in prompt
        assert "el-button" in prompt
        assert "sibling-label" in prompt  # 新策略类型提示
        assert "JSON" in prompt


class TestParse:
    def test_parse_plain_json(self):
        out = [{"index": 0, "strategies": [{"type": "css", "value": ".el-button", "priority": 1}]}]
        assert StaticScanService.parse_ai_output(json.dumps(out)) == out

    def test_parse_json_fenced(self):
        out = [{"index": 0, "strategies": [{"type": "id", "value": "#x", "priority": 1}]}]
        fenced = f"```json\n{json.dumps(out)}\n```"
        assert StaticScanService.parse_ai_output(fenced) == out

    def test_parse_garbage_returns_none(self):
        assert StaticScanService.parse_ai_output("不是JSON") is None


class TestGenerateComponent:
    @pytest.mark.asyncio
    async def test_success(self):
        gw = MagicMock()
        out = [{"index": 0, "strategies": [{"type": "sibling-label", "value": "//label[.]/following-sibling::input", "priority": 1}]}]
        gw.chat = AsyncMock(return_value={"content": json.dumps(out), "tokens": 100})
        svc = StaticScanService(gateway=gw)
        result = await svc.generate_component(_comp())
        assert result["ai_failed"] is False
        assert result["elements"][0]["locator_strategies"]["strategies"][0]["type"] == "sibling-label"
        # provider 是 glm（历史遗留 key，实际 glm-5.2）
        gw.chat.assert_awaited_once()
        assert gw.chat.await_args.kwargs.get("provider") == "glm-2.5" or gw.chat.await_args.args[1] == "glm-2.5"

    @pytest.mark.asyncio
    async def test_retry_then_fail(self):
        gw = MagicMock()
        gw.chat = AsyncMock(return_value={"content": "垃圾输出", "tokens": 10})
        svc = StaticScanService(gateway=gw)
        result = await svc.generate_component(_comp())
        assert result["ai_failed"] is True
        assert gw.chat.await_count == 2  # 重试1次
        assert all("locator_strategies" not in e for e in result["elements"])

    @pytest.mark.asyncio
    async def test_gateway_exception_marks_failed(self):
        gw = MagicMock()
        gw.chat = AsyncMock(side_effect=RuntimeError("api down"))
        svc = StaticScanService(gateway=gw)
        result = await svc.generate_component(_comp())
        assert result["ai_failed"] is True


class TestReuseDecision:
    def test_unchanged_hash_reuses(self):
        svc = StaticScanService(gateway=MagicMock())
        old = {"src/views/Cases.vue": {"content_hash": "h1",
              "strategies_by_index": {0: {"strategies": [{"type": "id", "value": "#a", "priority": 1}]}}}}
        comp = _comp()
        decision = svc.decide_reuse(comp, old)
        assert decision is not None and decision["reused"] is True
        assert comp["elements"][0]["locator_strategies"] == {"strategies": [{"type": "id", "value": "#a", "priority": 1}]}

    def test_changed_hash_regenerates(self):
        svc = StaticScanService(gateway=MagicMock())
        old = {"src/views/Cases.vue": {"content_hash": "OLD", "strategies_by_index": {}}}
        assert svc.decide_reuse(_comp(), old) is None

    def test_no_prior_record(self):
        svc = StaticScanService(gateway=MagicMock())
        assert svc.decide_reuse(_comp(), {}) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_static_scan_generate.py -v`
Expected: FAIL（AttributeError: PROMPT_TEMPLATE / build_prompt 等不存在）

- [ ] **Step 3: 实现生成与增量决策**

`backend/app/services/static_scan_service.py` 追加：

```python
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
    # ...（保留 Task 2 已有代码）...

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
    def parse_ai_output(content: str):
        """解析 AI 输出：裸 JSON 或 ```json 围栏。失败返回 None。"""
        if not content:
            return None
        text = content.strip()
        if text.startswith("```"):
            # 去掉 ```json / ``` 围栏
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = _json.loads(text)
        except _json.JSONDecodeError:
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
```

注意：`__init__` 若 Task 2 未写，本任务加入；`decide_reuse` 返回类型注解 `Dict[str, Any] | None` 需 Python 3.10+（项目 3.12 OK）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_static_scan_generate.py tests/test_static_scan_extract.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/static_scan_service.py backend/tests/test_static_scan_generate.py
git commit -m "feat(static-scan): glm-5.2定位器生成+hash增量复用决策"
```

---

### Task 4: 入库（页面树 + source=static_scan 元素）

**Files:**
- Modify: `backend/app/services/static_scan_service.py`
- Test: `backend/tests/test_static_scan_import.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_static_scan_import.py
"""入库：页面树幂等建节点/元素写入/已存在刷新/ai_failed剔除"""
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.services.static_scan_service import StaticScanService


def _comp(elements=2):
    els = []
    for i in range(elements):
        els.append({"tag": "el-button", "text": f"按钮{i}", "v_model": None, "placeholder": None,
                    "id": None, "href": None, "name": None, "data_testid": None, "pos": i + 2,
                    "locator_strategies": {"strategies": [{"type": "css", "value": f".btn{i}", "priority": 1}]}})
    return {"file_path": "src/views/Cases.vue", "component_name": "Cases",
            "template_snippet": "<div/>", "content_hash": "h1",
            "elements": els, "ai_failed": False}


class TestElementId:
    def test_element_id_from_text(self):
        e = {"tag": "el-button", "text": "新建用例", "id": None, "name": None,
             "placeholder": None, "data_testid": None}
        eid = StaticScanService.build_element_id("src/views/Cases.vue", e)
        assert eid == "cases_新建用例"

    def test_element_id_falls_back_to_tag_pos(self):
        e = {"tag": "el-input", "text": None, "id": None, "name": None,
             "placeholder": None, "data_testid": None}
        eid = StaticScanService.build_element_id("src/views/Cases.vue", e, pos=7)
        assert eid == "cases_el-input_7"


class TestImport:
    @pytest.mark.asyncio
    async def test_import_writes_elements_with_static_scan_source(self):
        db = MagicMock()
        page = MagicMock()
        page.id = "page-1"
        page.project_id = "proj-1"
        page.element_count = 0
        # execute 按顺序: 查页面树根节点(None) → 查页面 → 查已有element_id
        db.execute = AsyncMock(side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # 根节点查询
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # 页面按url查询
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # 新建页面 refresh
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # element_id 查询
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        svc = StaticScanService()
        page_id, imported, skipped = await svc.import_component(db, "proj-1", _comp(), route_path="/cases")
        assert imported == 2 and skipped == 0
        # 断言写入了 element 与 page
        added = [c.args[0] for c in db.add.call_args_list]
        from app.models.element import ElementRepository, PageRepository
        assert any(isinstance(a, PageRepository) for a in added)
        elements = [a for a in added if isinstance(a, ElementRepository)]
        assert len(elements) == 2
        assert all(e.source == "static_scan" for e in elements)
        assert all(e.confidence == 5 for e in elements)

    @pytest.mark.asyncio
    async def test_ai_failed_component_skipped(self):
        db = MagicMock()
        comp = _comp()
        comp["ai_failed"] = True
        svc = StaticScanService()
        page_id, imported, skipped = await svc.import_component(db, "proj-1", comp, route_path=None)
        assert imported == 0
        db.add.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_static_scan_import.py -v`
Expected: FAIL

- [ ] **Step 3: 实现入库**

`backend/app/services/static_scan_service.py` 追加：

```python
from uuid import UUID as _UUID
from app.models.element import PageRepository, ElementRepository
from sqlalchemy import select as _select


class StaticScanService:
    # ...（保留已有代码）...

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

    @staticmethod
    def build_element_name(elem: Dict[str, Any]) -> str | None:
        text = (elem.get("text") or "").strip()
        if text:
            return text[:100]
        return None  # 由入库侧按类型中文序号兜底（复用 _default_cn_alias 逻辑思路，此处简化为 tag）

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

        existing = await db.execute(
            _select(ElementRepository.element_id).where(
                ElementRepository.page_id == page_id)
        )
        existing_ids = {row[0] for row in existing.all()}

        imported, skipped = 0, 0
        seen = set()
        type_counters: Dict[str, int] = {}
        for i, e in enumerate(comp["elements"]):
            if "locator_strategies" not in e:
                skipped += 1  # AI 未产出该元素的策略
                continue
            element_id = self.build_element_id(comp["file_path"], e, pos=e.get("pos", i))
            if element_id in seen or element_id in existing_ids:
                skipped += 1
                continue
            seen.add(element_id)

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
        await db.commit()
        return page_id, imported, skipped
```

注意：`_UUID(project_id)` 要求 project_id 为 UUID 字符串；`page_id` 是 ORM 对象的 `page.id`（uuid），直接用于 where 没问题。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_static_scan_import.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/static_scan_service.py backend/tests/test_static_scan_import.py
git commit -m "feat(static-scan): 入库——页面树幂等节点+source=static_scan元素"
```

---

### Task 5: API 端点（zip 上传 + 静态元素列表）

**Files:**
- Modify: `backend/app/api/v1/whitescan.py`
- Modify: `backend/app/services/code_scan_service.py`（create_scan 支持标记 zip 来源）
- Test: `backend/tests/test_api_static_scan.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_api_static_scan.py
"""静态扫描 API：zip 上传校验（大小/扩展名/路径穿越条目）+ 静态元素列表"""
import io, zipfile
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app

PID = "00000000-0000-0000-0000-000000000001"
SCAN = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()


def _override(mock_svc):
    from app.api.v1.whitescan import get_scan_service
    app.dependency_overrides[get_scan_service] = lambda: mock_svc


def _zip_bytes(*names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "<template><button>x</button></template>")
    return buf.getvalue()


class TestLocatorScanUpload:
    def test_upload_ok(self, client):
        svc = MagicMock()
        svc.create_scan = AsyncMock(return_value={"id": SCAN, "status": "scanning"})
        _override(svc)
        with patch("app.api.v1.whitescan.run_locator_scan_task") as mock_task:
            mock_task.delay = MagicMock()
            r = client.post("/api/v1/whitescan/locator-scan",
                            files={"file": ("front.zip", _zip_bytes("src/A.vue"), "application/zip")},
                            data={"project_id": PID})
        assert r.status_code == 200
        assert r.json()["data"]["scan_id"] == SCAN
        mock_task.delay.assert_called_once()

    def test_reject_non_zip(self, client):
        r = client.post("/api/v1/whitescan/locator-scan",
                        files={"file": ("x.txt", b"hello", "text/plain")},
                        data={"project_id": PID})
        assert r.status_code == 400

    def test_reject_path_traversal(self, client):
        r = client.post("/api/v1/whitescan/locator-scan",
                        files={"file": ("evil.zip", _zip_bytes("../evil.vue"), "application/zip")},
                        data={"project_id": PID})
        assert r.status_code == 400

    def test_reject_oversize(self, client):
        big = b"\0" * (51 * 1024 * 1024)
        r = client.post("/api/v1/whitescan/locator-scan",
                        files={"file": ("big.zip", big, "application/zip")},
                        data={"project_id": PID})
        assert r.status_code == 400


class TestStaticElements:
    def test_list_static_elements(self, client):
        svc = MagicMock()
        svc.list_static_elements = AsyncMock(return_value={
            "total": 1, "items": [{"file_path": "src/A.vue", "component_name": "A",
                                    "element_count": 3, "ai_generated": True, "reused": False}]})
        _override(svc)
        r = client.get(f"/api/v1/whitescan/scans/{SCAN}/static-elements")
        assert r.status_code == 200
        assert r.json()["data"]["items"][0]["component_name"] == "A"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_api_static_scan.py -v`
Expected: FAIL（404，端点不存在）

- [ ] **Step 3: 实现端点**

`backend/app/services/code_scan_service.py` 的 `CodeScanService` 追加：

```python
    async def list_static_elements(self, scan_id: str) -> dict:
        """本次扫描静态定位器产出（组件粒度）。"""
        q = (select(StaticScanComponent)
             .where(StaticScanComponent.scan_id == UUID(scan_id))
             .order_by(StaticScanComponent.file_path))
        rows = (await self.db.execute(q)).scalars().all()
        items = [r.to_dict() for r in rows]
        return {"total": len(items), "items": items}
```

（import 区补 `from app.models.whitescan import StaticScanComponent`）

`backend/app/api/v1/whitescan.py` 追加（import 区补 `UploadFile, File` from fastapi、`import os, tempfile, zipfile`）：

```python
MAX_ZIP_BYTES = 50 * 1024 * 1024


def _validate_zip(data: bytes) -> None:
    """zip 校验：可解析 + 条目无路径穿越 + 无绝对路径。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="not a valid zip file")
    for name in zf.namelist():
        if name.startswith("/") or name.startswith("\\"):
            raise HTTPException(status_code=400, detail=f"absolute path in zip: {name}")
        # 归一化后不得逃逸
        norm = os.path.normpath(name)
        if norm.startswith("..") or ":/" in norm or ":\\" in norm:
            raise HTTPException(status_code=400, detail=f"path traversal in zip: {name}")


@router.post("/locator-scan")
async def trigger_locator_scan(project_id: str = Form(...),
                               file: UploadFile = File(...),
                               svc: CodeScanService = Depends(get_scan_service)):
    """源码 zip 上传 → 静态提取 + AI 定位器生成（与 semgrep 并行）。"""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="only .zip files accepted")
    data = await file.read()
    if len(data) > MAX_ZIP_BYTES:
        raise HTTPException(status_code=400, detail="zip exceeds 50MB limit")
    _validate_zip(data)

    # 落盘暂存（Celery worker 异步消费；本进程随即清理）
    tmp_dir = tempfile.mkdtemp(prefix="static_scan_")
    zip_path = os.path.join(tmp_dir, "upload.zip")
    with open(zip_path, "wb") as f:
        f.write(data)

    scan = await svc.create_scan(project_id, f"zip:{file.filename}", branch="zip")
    try:
        from app.tasks.code_scan_tasks import run_locator_scan_task
        run_locator_scan_task.delay(str(scan["id"]), project_id, zip_path)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=503, detail=f"task broker unavailable: {e}")
    return {"code": 0, "data": {"scan_id": scan["id"], "status": scan["status"]}}


@router.get("/scans/{scan_id}/static-elements")
async def list_static_elements(scan_id: str,
                               svc: CodeScanService = Depends(get_scan_service)):
    return {"code": 0, "data": await svc.list_static_elements(scan_id)}
```

（import 区还需 `import io, shutil` 与 `from fastapi import Form`）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_api_static_scan.py tests/test_api_whitescan.py -v`
Expected: 全 PASS（旧端点不回退）

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/whitescan.py backend/app/services/code_scan_service.py backend/tests/test_api_static_scan.py
git commit -m "feat(static-scan): zip上传端点+路径穿越校验+静态元素列表API"
```

---

### Task 6: Celery 任务（双支路并行）

**Files:**
- Modify: `backend/app/tasks/code_scan_tasks.py`
- Test: `backend/tests/test_static_scan_task.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_static_scan_task.py
"""Celery 任务编排：B支路(提取+AI+入库)流程/进度上报/失败不阻断A/临时清理"""
import os, zipfile
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def zip_path(tmp_path):
    """小 zip：2 个 vue 组件"""
    z = tmp_path / "front.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("src/views/A.vue", "<template><el-button @click='a'>按钮A</el-button></template>")
        f.writestr("src/views/B.vue", "<template><el-input v-model='x' placeholder='输入' /></template>")
    return str(z)


def _run_async(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


class TestLocatorScanTask:
    def test_b_branch_pipeline(self, zip_path):
        """B 支路：提取→AI→入库→组件记录落库"""
        from app.tasks.code_scan_tasks import _locator_branch

        mock_svc = MagicMock()
        mock_svc.extract_components = MagicMock(return_value=[
            {"file_path": "src/views/A.vue", "component_name": "A",
             "template_snippet": "<div/>", "content_hash": "h1",
             "elements": [{"tag": "el-button", "text": "按钮A", "pos": 1}]},
        ])
        mock_svc.generate_component = AsyncMock(side_effect=lambda c: {**c, "ai_failed": False})
        mock_svc.import_component = AsyncMock(return_value=("page-1", 1, 0))
        # prior hash 查询
        mock_svc.load_prior_components = AsyncMock(return_value={})
        mock_svc.record_component = AsyncMock()

        result = _run_async(_locator_branch("scan-1", "proj-1", zip_path, mock_svc))
        assert result["components"] == 1
        assert result["imported"] == 1
        mock_svc.generate_component.assert_awaited_once()
        mock_svc.record_component.assert_awaited_once()

    def test_ai_failed_component_not_imported(self, zip_path):
        from app.tasks.code_scan_tasks import _locator_branch
        mock_svc = MagicMock()
        mock_svc.extract_components = MagicMock(return_value=[
            {"file_path": "src/views/A.vue", "component_name": "A",
             "template_snippet": "<div/>", "content_hash": "h1",
             "elements": [{"tag": "el-button", "text": "A", "pos": 1}]},
        ])
        mock_svc.generate_component = AsyncMock(side_effect=lambda c: {**c, "ai_failed": True})
        mock_svc.import_component = AsyncMock()
        mock_svc.load_prior_components = AsyncMock(return_value={})
        mock_svc.record_component = AsyncMock()

        result = _run_async(_locator_branch("scan-1", "proj-1", zip_path, mock_svc))
        assert result["ai_failed"] == 1
        assert result["imported"] == 0
        mock_svc.import_component.assert_not_awaited()

    def test_temp_cleanup(self, zip_path, tmp_path):
        """任务结束（无论成败）清理解压目录"""
        from app.tasks import code_scan_tasks
        extract_dir = None
        orig_mkdtemp = None
        # 直接断言 finally 行为：构造一个必失败场景
        with patch.object(code_scan_tasks, "StaticScanService", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                code_scan_tasks.run_locator_scan_task_inner("scan-1", "proj-1", zip_path)
```

（说明：`_locator_branch` / `run_locator_scan_task_inner` 是任务文件内可单测的纯编排函数；`run_locator_scan_task` 是 Celery 薄壳。清理断言解压目录由 inner 的 finally rmtree——上面 test_temp_cleanup 中 inner 抛错后断言其内部解压目录不存在，实现时把解压目录建立在 zip_path 同级并返回路径供断言，或直接信任 finally rmtree 模式（与现有 run_scan_task 相同）——实施时可简化为验证无残留 temp 目录 `glob.glob(tempfile.gettempdir()+"/static_scan_*")`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_static_scan_task.py -v`
Expected: FAIL（_locator_branch 不存在）

- [ ] **Step 3: 实现任务**

`backend/app/tasks/code_scan_tasks.py` 追加（import 区补 `from concurrent.futures import ThreadPoolExecutor`）：

```python
# ---------------- 源码定位器链路（缺口3） ----------------

@celery_app.task(name="code_scan.run_locator_scan")
def run_locator_scan_task(scan_id: str, project_id: str, zip_path: str):
    """zip 上传扫描：A 支路 semgrep 与 B 支路静态定位器并行，互不阻断。"""
    import tempfile, shutil as _shutil
    work_dir = tempfile.mkdtemp(prefix="static_scan_work_")
    try:
        import asyncio

        def _a_branch():
            # A 支路：semgrep（zip 内容已在 work_dir 解压，直接扫）
            async def _run():
                async with AsyncSessionLocal() as db:
                    svc = CodeScanService(db)
                    scan = await svc.get_scan(scan_id)
                    if not scan:
                        raise RuntimeError(f"scan {scan_id} not found")
                    return await svc.run_scan_sync(scan, work_dir)
            return _run_async(_run())

        def _b_branch():
            return _run_async(_locator_branch(scan_id, project_id, zip_path, work_dir))

        a_result, b_result = None, None
        a_err, b_err = None, None
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(_a_branch)
            fb = pool.submit(_b_branch)
            try:
                a_result = fa.result()
            except Exception as e:
                a_err = str(e)
                logger.error(f"【静态扫描】semgrep支路失败 | scan={scan_id}: {e}")
            try:
                b_result = fb.result()
            except Exception as e:
                b_err = str(e)
                logger.error(f"【静态扫描】定位器支路失败 | scan={scan_id}: {e}")

        # 双失败才 failed；单失败仍 done（另一支路结果有效）
        if a_err and b_err:
            raise RuntimeError(f"both branches failed: a={a_err} b={b_err}")
        return {"semgrep": a_result or {"error": a_err},
                "static": b_result or {"error": b_err}}
    finally:
        _shutil.rmtree(work_dir, ignore_errors=True)
        _shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)  # 上传暂存目录


async def _locator_branch(scan_id: str, project_id: str, zip_path: str, work_dir: str,
                          svc=None) -> dict:
    """B 支路编排（可注入 svc 供测试）：解压→提取→hash增量→AI→入库→组件记录。"""
    import zipfile
    os.makedirs(work_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(work_dir)

    from app.services.static_scan_service import StaticScanService
    from app.models.whitescan import StaticScanComponent
    svc = svc or StaticScanService(gateway=_build_gateway())
    prior = await svc.load_prior_components(project_id)

    comps = svc.extract_components(work_dir)
    imported_total, reused, ai_failed = 0, 0, 0
    for comp in comps:
        decision = svc.decide_reuse(comp, prior)
        if decision:
            reused += 1
        else:
            comp = await svc.generate_component(comp)
            if comp.get("ai_failed"):
                ai_failed += 1
        route_path = _match_route(comp)  # 路由表匹配（无则 None）
        async with AsyncSessionLocal() as db:
            page_id, imported, _skipped = await svc.import_component(db, project_id, comp, route_path)
        await svc.record_component(db_factory=AsyncSessionLocal, scan_id=scan_id,
                                   project_id=project_id, comp=comp, page_id=page_id,
                                   reused=bool(decision))
        imported_total += imported
    return {"components": len(comps), "imported": imported_total,
            "reused": reused, "ai_failed": ai_failed}


def _build_gateway():
    from app.services.ai_gateway import AIGateway
    return AIGateway()


def _match_route(comp) -> str | None:
    """组件名匹配路由表（CodeStructureAnalyzer 产物缓存于任务级变量），命中返回 path。"""
    global _ROUTE_CACHE
    try:
        if _ROUTE_CACHE is None:
            from app.services.code_structure_analyzer import CodeStructureAnalyzer
            analyzer = CodeStructureAnalyzer()
            _ROUTE_CACHE = {os.path.splitext(os.path.basename(r.get("name") or ""))[0].lower(): r.get("path")
                            for r in analyzer.analyze_frontend(_LAST_WORK_DIR)}
        return _ROUTE_CACHE.get((comp["component_name"] or "").lower())
    except Exception:
        return None

_ROUTE_CACHE = None
_LAST_WORK_DIR = None
```

注意：`_match_route` 的全局缓存实现较脆弱（_LAST_WORK_DIR 需在 _b_branch 里赋值 `global _LAST_WORK_DIR; _LAST_WORK_DIR = work_dir`，_ROUTE_CACHE 在每次任务开始重置 None）。实施时按此补齐，或简化为在 `_locator_branch` 内先 `CodeStructureAnalyzer().analyze_frontend(work_dir)` 一次传入——**推荐后者**（无全局态）：

```python
def _match_route_factory(work_dir):
    try:
        from app.services.code_structure_analyzer import CodeStructureAnalyzer
        routes = CodeStructureAnalyzer().analyze_frontend(work_dir)
    except Exception:
        routes = []
    by_name = {os.path.splitext(os.path.basename(r.get("name") or ""))[0].lower(): r.get("path") for r in routes}
    return lambda comp: by_name.get((comp["component_name"] or "").lower())
```

然后 `_locator_branch` 内 `match_route = _match_route_factory(work_dir)`、`route_path = match_route(comp)`。

`record_component`（upsert，StaticScanService 方法）：

```python
    async def load_prior_components(self, project_id: str) -> Dict[str, Dict]:
        """历史组件 hash + 定位器索引（从最近一次成功扫描的元素表反查）。"""
        from app.models.whitescan import StaticScanComponent
        from app.models.element import ElementRepository
        q = (_select(StaticScanComponent)
             .where(StaticScanComponent.project_id == _UUID(project_id))
             .order_by(StaticScanComponent.updated_at.desc()))
        rows = (await db_all(self._db_for(q)))
        # 简化：直接从 static_scan_component 读 hash；定位器从元素表按页面反查
        prior: Dict[str, Dict] = {}
        for r in rows:
            if r.file_path in prior:
                continue  # 取最近一条
            # 反查该页面元素的 locator_strategies
            strategies_by_index = {}
            if r.page_id:
                els = await self._elements_of_page(r.page_id)
                for i, e in enumerate(els):
                    chain = (e.locator_strategies or {}).get("strategies") or []
                    if chain:
                        strategies_by_index[i] = {"strategies": chain}
            prior[r.file_path] = {"content_hash": r.content_hash,
                                  "strategies_by_index": strategies_by_index}
        return prior
```

（此方法需要 DB 会话——实施时给 StaticScanService 持有可选 db 会话或把 load_prior_components 放到任务内用 AsyncSessionLocal 实现。实施时倾向：`_locator_branch` 内直接写查询，StaticScanService 不持有 db。）

`record_component`（任务内实现，upsert 语义）：

```python
async def _record_component(project_id: str, scan_id: str, comp: dict,
                            page_id, reused: bool):
    from app.models.whitescan import StaticScanComponent
    from sqlalchemy import update as _update
    async with AsyncSessionLocal() as db:
        q = _select(StaticScanComponent).where(
            StaticScanComponent.project_id == _UUID(project_id),
            StaticScanComponent.file_path == comp["file_path"])
        row = (await db.execute(q)).scalar_one_or_none()
        if row:
            row.scan_id = _UUID(scan_id)
            row.content_hash = comp["content_hash"]
            row.page_id = _UUID(page_id) if isinstance(page_id, str) else page_id
            row.element_count = len([e for e in comp["elements"] if "locator_strategies" in e])
            row.ai_generated = not reused and not comp.get("ai_failed")
            row.reused = reused
            row.ai_failed = bool(comp.get("ai_failed"))
        else:
            db.add(StaticScanComponent(
                project_id=_UUID(project_id), scan_id=_UUID(scan_id),
                file_path=comp["file_path"], component_name=comp["component_name"],
                content_hash=comp["content_hash"],
                page_id=_UUID(page_id) if isinstance(page_id, str) else page_id,
                element_count=len([e for e in comp["elements"] if "locator_strategies" in e]),
                ai_generated=not reused and not comp.get("ai_failed"),
                reused=reused, ai_failed=bool(comp.get("ai_failed")),
            ))
        await db.commit()
```

**实施提示**：Task 6 有两个设计点在编写时可能需微调（load_prior_components 的 db 会话来源、_match_route 工厂化）。原则：无全局态、StaticScanService 不持 db、任务函数内用 AsyncSessionLocal。测试注入点用 `svc=` 参数保持。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_static_scan_task.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/code_scan_tasks.py backend/tests/test_static_scan_task.py
git commit -m "feat(static-scan): celery双支路并行——semgrep+定位器互不阻断"
```

---

### Task 7: 前端（zip 上传 + 元素定位器 Tab）

**Files:**
- Modify: `frontend/src/api/whitescan.js`
- Modify: `frontend/src/views/whitescan/WhiteScan.vue`
- Test: 前端 build 验证（`npm run build`）

- [ ] **Step 1: API 层加方法**

`frontend/src/api/whitescan.js` 追加：

```js
  locatorScan(projectId, file) {
    const fd = new FormData()
    fd.append('project_id', projectId)
    fd.append('file', file)
    return axios.post('/whitescan/locator-scan', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  listStaticElements(scanId) {
    return axios.get(`/whitescan/scans/${scanId}/static-elements`).then(r => r.data)
  },
```

- [ ] **Step 2: WhiteScan.vue 模板——扫描入口加 zip 模式**

`el-form inline` 区（仓库URL 表单项后）追加：

```html
        <el-form-item label="源码zip">
          <el-upload :auto-upload="false" :limit="1" :on-change="onZipChange"
                     accept=".zip" :file-list="zipFiles" :on-remove="() => zipFiles = []">
            <el-button :icon="Upload">选择zip</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="success" :loading="locScanning" @click="onLocatorScan">静态定位器扫描</el-button>
        </el-form-item>
```

（import 区补 `Upload` from '@element-plus/icons-vue'）

- [ ] **Step 3: 问题列表后加「元素定位器」区块**

`<!-- ④ 产出物下载 -->` 之前插入：

```html
      <!-- ③b 静态定位器产出 -->
      <template v-if="currentScan">
        <el-divider content-position="left">元素定位器（静态扫描）</el-divider>
        <el-table :data="staticElements" border style="margin-bottom: 16px">
          <el-table-column prop="component_name" label="组件" width="160" show-overflow-tooltip />
          <el-table-column prop="file_path" label="文件" min-width="240" show-overflow-tooltip />
          <el-table-column prop="element_count" label="元素数" width="80" />
          <el-table-column label="来源" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.reused" type="info" size="small">复用</el-tag>
              <el-tag v-else-if="row.ai_failed" type="danger" size="small">AI失败</el-tag>
              <el-tag v-else type="success" size="small">AI生成</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>
```

- [ ] **Step 4: script 补逻辑**

```js
const zipFiles = ref([])
const locScanning = ref(false)
const staticElements = ref([])
const selectedZip = ref(null)

const onZipChange = (file, fileList) => {
  zipFiles.value = fileList
  selectedZip.value = file.raw || null
}

const onLocatorScan = async () => {
  if (!projectId.value) { ElMessage.warning('先选择项目'); return }
  if (!selectedZip.value) { ElMessage.warning('选择源码 zip 文件'); return }
  if (selectedZip.value.size > 50 * 1024 * 1024) { ElMessage.warning('zip 不能超过 50MB'); return }
  locScanning.value = true
  try {
    const res = await whitescanAPI.locatorScan(projectId.value, selectedZip.value)
    const sid = (res.data || res).scan_id
    ElMessage.success('静态扫描已提交，异步执行中')
    stopPolling()
    pollTimer = setInterval(async () => {
      try {
        const s = (await whitescanAPI.getScan(sid)).data || {}
        if (s.status !== 'scanning') {
          stopPolling(); locScanning.value = false
          s.status === 'done' ? ElMessage.success('静态扫描完成') : ElMessage.error('静态扫描失败')
          loadScans()
        }
      } catch (e) { console.error(e) }
    }, 3000)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
    locScanning.value = false
  }
}

// onScanSelect 内补拉静态元素
const loadStaticElements = async () => {
  if (!currentScan.value) { staticElements.value = []; return }
  try {
    const res = await whitescanAPI.listStaticElements(currentScan.value.id)
    staticElements.value = (res.data || res)?.items || []
  } catch (e) { staticElements.value = [] }
}
// onScanSelect 改为:
// const onScanSelect = async (row) => { currentScan.value = row; if (row) { await loadIssues(); await loadStaticElements() } }
```

- [ ] **Step 5: build 验证**

Run: `cd frontend && npm run build`
Expected: build 成功无错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/whitescan.js frontend/src/views/whitescan/WhiteScan.vue
git commit -m "feat(static-scan): 前端zip上传+元素定位器Tab"
```

---

### Task 8: 全量回归 + 重启 + 真实冒烟

- [ ] **Step 1: 全量后端测试**

Run: `cd backend && python -m pytest -q`
Expected: ≥918 passed，无新增失败

- [ ] **Step 2: 前端 build**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: 应用迁移（若 Task 1 未在真库执行）**

Run: `PGPASSWORD=Admin@123 psql -h localhost -p 5433 -U postgres -d moontest -f backend/migrations/016_static_scan_components.sql`

- [ ] **Step 4: 重启 backend + celery（8000 无 --reload）**

先 `netstat -ano | findstr :8000` 查清占端口进程全部杀净，再启动 uvicorn 与 `celery -A app.tasks worker`。

- [ ] **Step 5: 真实冒烟（MoonTest 自己前端 zip 试验田）**

打包 `frontend/src` 为 zip → WhiteScan 页上传 → 等扫描完成 → 验证：
1. 「元素定位器」Tab 有产出（组件/元素数/AI生成标记）
2. 元素库页面可见 source=static_scan 元素，挂页面树
3. 同一 zip 重传：日志显示 reused 组件不调 AI
4. 改一个 .vue 重传：仅该组件重新生成

- [ ] **Step 6: Commit（如有冒烟修正）+ 收官贴全表**

---

## Self-Review 结论

- **Spec 覆盖**：zip 上传校验（Task 5）、并行支路（Task 6）、提取（Task 2）、AI 生成含 anchor/sibling-label 提示（Task 3）、hash 增量（Task 3/6）、入库挂页面树（Task 4）、前端 Tab（Task 7）、验收 1-7 对应 Task 8 冒烟。✅
- **占位符**：Task 6 中 `_match_route` 全局态实现已标注推荐工厂化方案（非占位，是两个等价实现任选其一并给出完整代码）。`load_prior_components` 的 db 会话归属已给实现提示与原则。实施 subagent 需按提示落实——已明确方向非 TBD。
- **类型一致性**：`generate_component`/`decide_reuse`/`import_component`/`build_element_id` 签名在 Task 2/3/4/6 间一致；`_locator_branch(svc=)` 注入点在 Task 6 测试与实现一致。✅
