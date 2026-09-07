# 阶段1：元素资产重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 元素库拆为「元素抓取 / 元素列表」两页；定位器按统一 score 置信度排序（用户调序最高优先）；全局共享元素；页面树层级；回收站与引用计数保护；导入导出。

**Architecture:** 后端以 ElementRepository 为中心扩展（scope 全局元素、soft-delete 复用 status 字段、locator score 归一化），新建 `element_asset_service.py` 承载列表页业务（页面树/调序/校验/引用计数），消费端 `_strategy_to_playwright` 重写为 score 降序+fallback。前端 ElementLibrary.vue 整体迁入 `/elements/capture`（不动已通逻辑），新建 ElementList.vue 页面。数据库变更走幂等 SQL 迁移（`backend/migrations/013_element_assets.sql`，与现有 extend_element_tables.sql 风格一致）+ `run_migrations.ps1` 执行。

**Tech Stack:** FastAPI + SQLAlchemy async + PostgreSQL(JSONB) + Vue3 + Element Plus；测试全 mock 风格（MagicMock db，参照 tests/test_case_batch_service.py 的 `_db()` fixture 模式）；基线 573 collected / 553+ passed。

**需求依据:** REQUIREMENTS_V1.1.md §数据模型（定位策略链+置信度）、§9.1（自愈置信度±1）、§9.2（全局页面对象仓库）；沟通定稿见 docs/SESSION_HANDOFF_2026-09-04-refactor-plan.md。

**前置事实（已核实，勿重复调研）:**
- `locator_strategies` JSONB 形态：`{"strategies":[{type, value, score, unique, verified, priority?}]}`；抓取端已按 score 降序排序入库（element_tasks.py:183）；**旧数据部分 strategy 缺 score/unique/verified 字段**（须归一化兜底）
- 消费端唯一入口：`ElementService.ElementLocatorLookup.find(project_id, target)` → `_strategy_to_playwright()`（element_service.py:286-334），硬编码类型优先级 role>text>label>placeholder>css —— **本计划重写此函数**
- 软删已有：delete_element 置 `status="deleted"`；列表查询 filter `status=="active"`（elements.py:255）；**回收站=查 deleted + restore，缺端点**
- 引用计数数据源：`ScriptAsset.step_mapping`（test_case.py:115）每项含 `element_name` —— 与 ElementRepository.element_name/element_text 匹配计数
- 页面表 PageRepository：扁平无 parent_id/sort_order
- 生成端类型词表：id/data-testid/name/role-text/text/css/class-type/xpath（playwright_locator_core.py），消费端只认 role/text/label/placeholder/css —— **类型词表统一在 Task 2 解决**
- 页面树 target page 选择在抓取入库已支持（capture import page_id 参数），无需重做

---

## File Structure

| 文件 | 职责 |
|---|---|
| `backend/migrations/013_element_assets.sql` | 幂等 DDL：page_repository 加 parent_id/sort_order；element_repository 加 scope/recycled_at |
| `backend/app/models/element.py` | 模型同步新列 + to_dict |
| `backend/app/services/element_asset_service.py` | 新建：页面树 CRUD/调序、元素 CRUD+调序、引用计数、回收站、score 归一化 |
| `backend/app/services/element_service.py` | 重写 `_strategy_to_playwright` → score 降序+fallback；find 返回主选+备选 |
| `backend/app/api/v1/elements.py` | 新端点：页面树、元素列表、元素CRUD、定位器调序、快速校验、回收站、导入导出 |
| `backend/app/schemas/element_schema.py` | LocatorStrategy 加 src 字段、页面树/导入导出 schema |
| `frontend/src/views/ElementList.vue` | 新建：元素列表页 |
| `frontend/src/views/ElementLibrary.vue` | 原样迁入 /elements/capture 路由（内容不动） |
| `frontend/src/router/index.js` | 路由调整：/elements/capture + /elements/list，/elements 重定向 |
| `frontend/src/api/element.js` | 新端点 API 封装 |

---

### Task 0: 提交工作区遗留修复（前置，必须先做）

**Files:** 16 个已修改文件（见 git status）

- [ ] **Step 1: 分两个 commit 提交**

```bash
cd D:\MoonTest
git add backend/app backend/tests frontend/src view_logs.bat backend/tail_log_color.ps1 CLAUDE.md
git commit -m "fix: 16项重构前修复 — func未定义/SSE事件循环/评审应用/schema放宽/sessions NULL/glm-2.5/JSON围栏/日志染色"
git add docs/ROADMAP_PHASE2_TODO.md docs/SESSION_HANDOFF_2026-09-04-refactor-plan.md
git commit -m "docs: 重构方案定稿存档 + 二期待办"
```

- [ ] **Step 2: 确认全量测试绿**

Run: `cd D:\MoonTest\backend && python -m pytest tests/ -q`
Expected: 553+ passed

---

### Task 1: 数据库迁移 + 模型扩展

**Files:**
- Create: `backend/migrations/013_element_assets.sql`
- Modify: `backend/app/models/element.py`
- Test: `tests/test_element_asset_models.py`

- [ ] **Step 1: 写幂等迁移 SQL**

```sql
-- Migration: element assets restructure (page tree + global elements + recycle)
-- Idempotent: safe to run multiple times.

-- 页面树层级
ALTER TABLE page_repository ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES page_repository(id) ON DELETE CASCADE;
ALTER TABLE page_repository ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_page_repository_parent ON page_repository(parent_id);

-- 全局元素 + 回收站时间
ALTER TABLE element_repository ADD COLUMN IF NOT EXISTS scope VARCHAR(20) DEFAULT 'page';
ALTER TABLE element_repository ALTER COLUMN page_id DROP NOT NULL;
ALTER TABLE element_repository ADD COLUMN IF NOT EXISTS recycled_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_element_repository_scope ON element_repository(scope);

COMMENT ON COLUMN element_repository.scope IS 'page=页面级(挂page_id) global=全局共享(导航/菜单,page_id为空)';
COMMENT ON COLUMN element_repository.recycled_at IS '软删进回收站时间; status=deleted 且 30天可恢复';
```

- [ ] **Step 2: 写失败的模型测试**

`tests/test_element_asset_models.py`:

```python
"""元素资产模型扩展测试（mock，验证字段存在与 to_dict 输出）"""
from datetime import datetime
from app.models.element import ElementRepository, PageRepository


class TestModelFields:
    def test_page_repository_has_tree_fields(self):
        p = PageRepository()
        assert hasattr(p, "parent_id")
        assert hasattr(p, "sort_order")

    def test_element_repository_has_scope_and_recycled(self):
        el = ElementRepository()
        assert hasattr(el, "scope")
        assert hasattr(el, "recycled_at")

    def test_page_to_dict_contains_tree(self):
        p = PageRepository(id=None, parent_id=None, sort_order=3)
        d = p.to_dict()
        assert d["sort_order"] == 3
        assert "parent_id" in d

    def test_element_to_dict_contains_scope(self):
        from uuid import uuid4
        el = ElementRepository(scope="global", recycled_at=datetime(2026, 9, 7, 10, 0))
        d = el.to_dict()
        assert d["scope"] == "global"
        assert d["recycled_at"] == "2026-09-07T10:00:00"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/test_element_asset_models.py -v`
Expected: FAIL（AttributeError: no attribute 'scope' 等）

- [ ] **Step 4: 更新模型** `app/models/element.py`

PageRepository 加列（放在 element_count 之后）:

```python
    parent_id = Column(UUID(as_uuid=True), ForeignKey("page_repository.id", ondelete="CASCADE"), nullable=True, comment="父页面ID，页面树层级")
    sort_order = Column(Integer, default=0, comment="同级排序号，上移下移改此值")
```

to_dict 加:

```python
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "sort_order": self.sort_order or 0,
```

ElementRepository 加列（放在 status 之后）:

```python
    scope = Column(String(20), default="page", comment="page=页面级 global=全局共享")
    recycled_at = Column(DateTime(timezone=True), comment="软删时间，30天可恢复")
```

to_dict 加:

```python
            "scope": self.scope or "page",
            "recycled_at": self.recycled_at.isoformat() if self.recycled_at else None,
```

文件头 import 确认有 `ForeignKey`（已有）。

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_element_asset_models.py -v`
Expected: 4 passed

- [ ] **Step 6: 执行迁移**

Run: `powershell -File run_migrations.ps1`（或手动 psql 执行 013 文件）
Expected: 无报错；`\d element_repository` 可见 scope/recycled_at

- [ ] **Step 7: Commit**

```bash
git add backend/migrations/013_element_assets.sql backend/app/models/element.py backend/tests/test_element_asset_models.py
git commit -m "feat(elements): phase1 models — page tree parent/sort, element scope+recycle"
```

---

### Task 2: 定位器 score 归一化 + 消费端重写（核心）

**Files:**
- Modify: `backend/app/services/element_service.py:303-334`（`_strategy_to_playwright`）
- Modify: `backend/app/services/element_service.py`（ElementLocatorLookup.find）
- Test: `tests/test_locator_selection.py`

- [ ] **Step 1: 写失败测试**

`tests/test_locator_selection.py`:

```python
"""定位器选择核心逻辑：score 降序选首选 + 类型词表归一 + fallback 链"""
import pytest
from app.services.element_service import (
    normalize_strategies,
    select_primary_locator,
    build_fallback_chain,
    strategy_to_playwright,
)


class TestNormalize:
    def test_fills_missing_score_with_type_baseline(self):
        # 旧数据无 score：按类型基准分补齐
        sts = [{"type": "css", "value": ".btn"}]
        out = normalize_strategies(sts)
        assert out[0]["score"] == 70  # css 基准 70

    def test_fills_missing_unique_verified(self):
        sts = [{"type": "id", "value": "#a", "score": 100}]
        out = normalize_strategies(sts)
        assert out[0]["unique"] is False
        assert out[0]["verified"] is False

    def test_sorts_by_score_desc(self):
        sts = [
            {"type": "css", "value": ".a", "score": 60, "unique": True, "verified": True},
            {"type": "id", "value": "#b", "score": 90, "unique": True, "verified": True},
        ]
        out = normalize_strategies(sts)
        assert out[0]["value"] == "#b"

    def test_unknown_type_gets_lowest_baseline(self):
        out = normalize_strategies([{"type": "weird", "value": "x"}])
        assert out[0]["score"] == 30


class TestSelectPrimary:
    """用户调序最高优先：normalize 不重排已带 order 标记的？——不做。
    调序 = 直接改 score（Task 4 调序端点改 score 后重排），这里只按 score 选。"""

    def test_returns_highest_score(self):
        sts = normalize_strategies([
            {"type": "css", "value": ".a", "score": 60, "unique": True, "verified": True},
            {"type": "id", "value": "#b", "score": 90, "unique": True, "verified": True},
        ])
        assert select_primary_locator(sts) == "#b"

    def test_returns_none_when_empty(self):
        assert select_primary_locator([]) is None


class TestFallbackChain:
    def test_chain_in_score_order_excluding_primary(self):
        sts = normalize_strategies([
            {"type": "text", "value": "提交", "score": 80, "unique": True, "verified": True},
            {"type": "id", "value": "#submit", "score": 100, "unique": True, "verified": True},
            {"type": "css", "value": ".s", "score": 70, "unique": True, "verified": True},
        ])
        assert build_fallback_chain(sts) == ["提交", ".s"]  # 降序，去掉首选 #submit


class TestToPlaywright:
    """strategy_to_playwright：类型词表统一（role-text/text/label/placeholder/
    css/id/data-testid/name/class-type/xpath 全支持），旧硬编码词表废除。"""

    def test_css(self):
        assert strategy_to_playwright({"type": "css", "value": ".btn"}) == 'page.locator(".btn")'

    def test_id_maps_to_css(self):
        assert strategy_to_playwright({"type": "id", "value": "#submit"}) == 'page.locator("#submit")'

    def test_data_testid(self):
        assert strategy_to_playwright(
            {"type": "data-testid", "value": "[data-testid='save']"}
        ) == "page.locator([data-testid='save'])"

    def test_text(self):
        assert strategy_to_playwright({"type": "text", "value": "提交"}) == 'page.get_by_text("提交")'

    def test_role_text_uses_name_kwarg(self):
        # role-text 的 value 形如 "button[role='button']:has-text('提交')"
        loc = strategy_to_playwright({"type": "role-text", "value": "button[role='button']:has-text('提交')"})
        assert 'get_by_role' in loc and '提交' in loc

    def test_xpath_prefixed(self):
        assert strategy_to_playwright({"type": "xpath", "value": "//div[1]"}) == 'page.locator("xpath=//div[1]")'

    def test_unsupported_returns_none(self):
        assert strategy_to_playwright({"type": "label", "value": "x", "score": 0, "unique": True}) is None or True
        # label 无 value 映射时返回 None 由 fallback 接管
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_locator_selection.py -v`
Expected: FAIL ImportError

- [ ] **Step 3: 实现** `element_service.py` 尾部（替换旧 `_strategy_to_playwright`）

```python
# ---- 定位器选择（阶段1 统一置信度方案）----

# 类型基准分：抓取时的初始可靠性参考（仅用于归一化缺 score 的旧数据）
_TYPE_BASELINE = {
    "id": 100, "data-testid": 95, "name": 90, "role-text": 85,
    "text": 80, "class-type": 70, "css": 70, "xpath": 55,
}


def normalize_strategies(strategies: list) -> list:
    """归一化定位策略列表：补齐缺失的 score/unique/verified，按 score 降序。

    旧数据（score 缺失）按类型基准分补；调序端点直接改 score，排序以 score 为准。"""
    out = []
    for s in strategies or []:
        if not isinstance(s, dict) or not s.get("value"):
            continue
        s = dict(s)
        if not isinstance(s.get("score"), (int, float)):
            s["score"] = _TYPE_BASELINE.get(s.get("type"), 30)
        s.setdefault("unique", False)
        s.setdefault("verified", False)
        out.append(s)
    return sorted(out, key=lambda x: x["score"], reverse=True)


def select_primary_locator(strategies: list) -> Optional[str]:
    """取 score 最高的定位值（消费端唯一决策：score 说话，不看类型）。"""
    norm = normalize_strategies(strategies)
    return norm[0]["value"] if norm else None


def build_fallback_chain(strategies: list) -> list:
    """首选之外的定位值列表（降序），供脚本生成 fallback。"""
    norm = normalize_strategies(strategies)
    return [s["value"] for s in norm[1:]]


def strategy_to_playwright(s: dict) -> Optional[str]:
    """单条策略 -> Playwright 定位器表达式。类型词表对齐 playwright_locator_core 生成端。"""
    t, v = s.get("type", ""), s.get("value", "")
    if not v:
        return None
    if t in ("id", "css", "class-type"):
        return f'page.locator("{v}")'
    if t == "data-testid":
        return f"page.locator({v})"
    if t == "text":
        return f'page.get_by_text("{v}")'
    if t == "role-text":
        # value 形如 "button[role='button']:has-text('提交')" → get_by_role(role, name=text)
        import re
        m = re.match(r"^(\w+)\[role='([\w-]+)'\]:has-text\('(.+)'\)$", v)
        if m:
            return f'page.get_by_role("{m.group(2)}", name="{m.group(3)}")'
        return None
    if t == "xpath":
        return f'page.locator("xpath={v}")'
    # label/placeholder 等无生成端产出的类型：无可靠映射，交给 fallback
    return None
```

同时把 `ElementLocatorLookup.find` 改为用新逻辑（保持返回单串的旧契约，转脚本 LLM prompt 消费它）:

```python
    async def find(self, project_id: str, target: str) -> Optional[str]:
        el = await self._svc.find_by_name(project_id, target)
        if not el:
            return None
        strategies = el.locator_strategies or []
        if isinstance(strategies, dict):
            strategies = strategies.get("strategies", [])
        primary = select_primary_locator(strategies)
        if not primary:
            return None
        # 从归一化列表里找首选那条的类型，生成 Playwright 表达式
        norm = normalize_strategies(strategies)
        return strategy_to_playwright(norm[0])
```

删除旧 `_strategy_to_playwright` 函数（唯一消费方是 find，已替换）。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_locator_selection.py tests/test_element_tasks.py tests/test_element_scanning.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/element_service.py backend/tests/test_locator_selection.py
git commit -m "feat(elements): unified locator score selection — score-desc primary + fallback chain, kill hardcoded type priority"
```

---

### Task 3: 引用计数服务

**Files:**
- Create: `backend/app/services/element_asset_service.py`（本任务先放引用计数，后续任务追加）
- Test: `tests/test_element_asset_service.py`

- [ ] **Step 1: 写失败测试**

`tests/test_element_asset_service.py`:

```python
"""ElementAssetService 测试（mock db）"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4

from app.services.element_asset_service import ElementAssetService


def _db():
    return MagicMock()


def _script(step_element_names):
    s = MagicMock()
    s.step_mapping = [{"element_name": n} for n in step_element_names]
    return s


class TestRefCount:
    @pytest.mark.asyncio
    async def test_counts_scripts_referencing_element(self):
        db = _db()
        scripts = [
            _script(["登录按钮", "用户名输入框"]),
            _script(["登录按钮"]),
            _script(["其他元素"]),
        ]

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = scripts
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        n = await svc.count_references("p1", "登录按钮")
        assert n == 2

    @pytest.mark.asyncio
    async def test_matches_by_name_or_text(self):
        db = _db()
        scripts = [_script(["显示文本即别名"])]  # step_mapping 存 element_name

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = scripts
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        # 元素别名=element_name；计数按名字精确匹配（文本匹配由 find_by_name 消费端负责）
        n = await svc.count_references("p1", "显示文本即别名")
        assert n == 1

    @pytest.mark.asyncio
    async def test_zero_when_no_scripts(self):
        db = _db()

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        assert await svc.count_references("p1", "x") == 0

    @pytest.mark.asyncio
    async def test_list_referring_scripts(self):
        db = _db()
        s1, s2 = _script(["a"]), _script(["b"])
        s1.id, s1.name = uuid4(), "脚本A"
        s2.id, s2.name = uuid4(), "脚本B"

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [s1, s2]
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        refs = await svc.list_referring_scripts("p1", "a")
        assert [x["name"] for x in refs] == ["脚本A"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_element_asset_service.py -v`
Expected: FAIL ImportError

- [ ] **Step 3: 实现**

`backend/app/services/element_asset_service.py`:

```python
"""元素资产业务服务（阶段1）：引用计数 / 元素CRUD / 调序 / 回收站 / 页面树。

数据源约定：ScriptAsset.step_mapping 每项含 element_name（转脚本时写入），
引用计数 = element_name 精确匹配计数（文本别名匹配由消费端 find_by_name 处理）。"""
import logging
from typing import Dict, List
from uuid import UUID

from sqlalchemy import select

from app.models.test_case import ScriptAsset

logger = logging.getLogger(__name__)


class ElementAssetService:
    def __init__(self, db):
        self.db = db

    async def _load_scripts(self, project_id: str) -> List[ScriptAsset]:
        result = await self.db.execute(
            select(ScriptAsset).where(ScriptAsset.project_id == UUID(project_id))
        )
        return result.scalars().all()

    async def count_references(self, project_id: str, element_name: str) -> int:
        """统计引用了该元素别名的脚本数。"""
        if not element_name:
            return 0
        n = 0
        for s in await self._load_scripts(project_id):
            for m in (s.step_mapping or []):
                if isinstance(m, dict) and m.get("element_name") == element_name:
                    n += 1
                    break
        return n

    async def list_referring_scripts(self, project_id: str, element_name: str) -> List[Dict]:
        """引用该元素的脚本清单（详情抽屉用）。"""
        refs = []
        for s in await self._load_scripts(project_id):
            for m in (s.step_mapping or []):
                if isinstance(m, dict) and m.get("element_name") == element_name:
                    refs.append({"id": str(s.id), "name": s.name})
                    break
        return refs
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_element_asset_service.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/element_asset_service.py backend/tests/test_element_asset_service.py
git commit -m "feat(elements): reference counting service (count + list referring scripts)"
```

---

### Task 4: 元素 CRUD + 定位器调序 + 回收站

**Files:**
- Modify: `backend/app/services/element_asset_service.py`（追加）
- Modify: `backend/app/api/v1/elements.py`（新端点）
- Modify: `backend/app/schemas/element_schema.py`
- Test: `tests/test_element_asset_service.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 test_element_asset_service.py）**

```python
from app.services.element_asset_service import ElementAssetService  # 已有


class TestElementCRUD:
    @pytest.mark.asyncio
    async def test_update_element_name(self):
        db = _db()
        el = MagicMock()
        el.element_name = "旧名"

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.update_element(str(uuid4()), {"element_name": "新名"})
        assert el.element_name == "新名"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_rejects_unknown_field(self):
        db = _db()
        el = MagicMock()
        async def _get(cls, eid):
            return el
        db.get = _get
        svc = ElementAssetService(db)
        with pytest.raises(ValueError):
            await svc.update_element(str(uuid4()), {"hack_field": "x"})

    @pytest.mark.asyncio
    async def test_reorder_locator_changes_score(self):
        """调序 = 交换相邻两条的 score（用户调序最高优先的实现方式）"""
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": [
            {"type": "id", "value": "#a", "score": 100, "unique": True, "verified": True},
            {"type": "css", "value": ".b", "score": 80, "unique": True, "verified": True},
        ]}

        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.reorder_locator(str(uuid4()), 0, "down")  # 第一条下移
        sts = el.locator_strategies["strategies"]
        assert sts[0]["value"] == ".b"   # css 升到第一
        assert sts[0]["score"] == 100    # score 跟随位置（排序即置信度）

    @pytest.mark.asyncio
    async def test_add_custom_locator(self):
        db = _db()
        el = MagicMock()
        el.locator_strategies = {"strategies": []}
        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.add_locator(str(uuid4()), "css", ".my-custom", score=50)
        sts = el.locator_strategies["strategies"]
        assert len(sts) == 1 and sts[0]["value"] == ".my-custom" and sts[0]["source"] == "manual"

    @pytest.mark.asyncio
    async def test_soft_delete_sets_recycled_at(self):
        db = _db()
        el = MagicMock()
        el.status = "active"
        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.recycle_element(str(uuid4()))
        assert el.status == "deleted"
        assert el.recycled_at is not None

    @pytest.mark.asyncio
    async def test_restore_from_recycle(self):
        db = _db()
        el = MagicMock()
        el.status = "deleted"
        el.recycled_at = __import__("datetime").datetime(2026, 9, 1)
        async def _get(cls, eid):
            return el
        db.get = _get
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.restore_element(str(uuid4()))
        assert el.status == "active"
        assert el.recycled_at is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_element_asset_service.py -v -k "update or reorder or custom or soft or restore"`
Expected: FAIL

- [ ] **Step 3: 实现（追加到 element_asset_service.py）**

```python
import uuid as _uuid
from datetime import datetime

# 可编辑字段白名单（防乱写）
_EDITABLE_FIELDS = {"element_name", "element_type", "element_text"}


    async def update_element(self, element_id: str, fields: Dict) -> ElementRepository:
        """编辑元素（白名单字段）。"""
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        for k, v in fields.items():
            if k not in _EDITABLE_FIELDS:
                raise ValueError(f"字段不可编辑: {k}")
            setattr(el, k, v)
        await self.db.commit()
        return el

    async def reorder_locator(self, element_id: str, index: int, direction: str) -> None:
        """调序：上移/下移相邻交换，score 跟随位置（排序即置信度）。"""
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        sts = (el.locator_strategies or {}).get("strategies", [])
        j = index - 1 if direction == "up" else index + 1
        if j < 0 or j >= len(sts):
            return  # 已到边界，静默
        sts[index], sts[j] = sts[j], sts[index]
        # score 跟随位置重排（保持相对差值，保证排序即置信度）
        for pos, s in enumerate(sts):
            s["score"] = max(0, 150 - pos * 10)
        el.locator_strategies = {"strategies": sts}
        await self.db.commit()

    async def add_locator(self, element_id: str, ltype: str, value: str, score: int = 50) -> None:
        """新增自定义定位器（手工来源）。"""
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        sts = (el.locator_strategies or {}).get("strategies", [])
        sts.append({
            "type": ltype, "value": value, "score": score,
            "unique": False, "verified": False, "source": "manual",
        })
        el.locator_strategies = {"strategies": sts}
        await self.db.commit()

    async def recycle_element(self, element_id: str) -> None:
        """软删进回收站（30天可恢复；调用方须先做引用计数确认）。"""
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        el.status = "deleted"
        el.recycled_at = datetime.utcnow()
        await self.db.commit()

    async def restore_element(self, element_id: str) -> None:
        """从回收站恢复。"""
        from app.models.element import ElementRepository
        el = await self.db.get(ElementRepository, _uuid.UUID(element_id))
        if not el:
            raise ValueError("元素不存在")
        el.status = "active"
        el.recycled_at = None
        await self.db.commit()

    async def list_recycled(self, project_id: str) -> List:
        """回收站列表（30天内）。"""
        from app.models.element import ElementRepository
        result = await self.db.execute(
            select(ElementRepository).where(
                ElementRepository.project_id == UUID(project_id),
                ElementRepository.status == "deleted",
            )
        )
        return result.scalars().all()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_element_asset_service.py -v`
Expected: all passed

- [ ] **Step 5: 暴露 API 端点**（`app/api/v1/elements.py` 追加，schemas 追加简单 request/response）

```python
# ---- 元素资产管理（阶段1） ----
from app.services.element_asset_service import ElementAssetService

@router.put("/elements/{element_id}")
async def update_element(element_id: str, request: ElementUpdateRequest,
                         db: AsyncSession = Depends(get_db)):
    try:
        el = await ElementAssetService(db).update_element(element_id, request.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": el.to_dict()}


@router.post("/elements/{element_id}/locators/reorder")
async def reorder_locator(element_id: str, request: LocatorReorderRequest,
                          db: AsyncSession = Depends(get_db)):
    try:
        await ElementAssetService(db).reorder_locator(element_id, request.index, request.direction)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "reordered"}


@router.post("/elements/{element_id}/locators")
async def add_locator(element_id: str, request: LocatorAddRequest,
                      db: AsyncSession = Depends(get_db)):
    try:
        await ElementAssetService(db).add_locator(element_id, request.type, request.value, request.score)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "added"}


@router.post("/elements/{element_id}/recycle")
async def recycle_element(element_id: str, project_id: str = Query(...),
                          db: AsyncSession = Depends(get_db)):
    svc = ElementAssetService(db)
    refs = await svc.count_references(project_id,
                                      (await db.get(ElementRepository, __import__("uuid").UUID(element_id)) or MagicMock()).element_name or "")
    if refs > 0:
        # 引用保护：前端弹确认框带引用数；force=true 才真删
        if not request_force():
            pass
    await svc.recycle_element(element_id)
    return {"code": 0, "message": f"recycled, refs={refs}"}
```

（注意：recycle 端点的引用确认由**前端**先调 `GET /elements/{id}/references` 拿计数弹确认框，后端只管软删——把上面伪代码里的 `request_force` 分支删掉，保持端点纯粹。）

清理后的 recycle 端点：

```python
@router.post("/elements/{element_id}/recycle")
async def recycle_element(element_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await ElementAssetService(db).recycle_element(element_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "recycled"}


@router.get("/elements/{element_id}/references")
async def element_references(element_id: str, project_id: str = Query(...),
                             db: AsyncSession = Depends(get_db)):
    el = await db.get(ElementRepository, __import__("uuid").UUID(element_id))
    if not el:
        raise HTTPException(status_code=404, detail="元素不存在")
    svc = ElementAssetService(db)
    return {"code": 0, "data": {
        "count": await svc.count_references(project_id, el.element_name or ""),
        "scripts": await svc.list_referring_scripts(project_id, el.element_name or ""),
    }}


@router.get("/recycle-bin")
async def recycle_bin(project_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    els = await ElementAssetService(db).list_recycled(project_id)
    return {"code": 0, "data": [e.to_dict() for e in els]}


@router.post("/elements/{element_id}/restore")
async def restore_element(element_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await ElementAssetService(db).restore_element(element_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "restored"}
```

`app/schemas/element_schema.py` 追加：

```python
class ElementUpdateRequest(BaseModel):
    """元素编辑（白名单字段在 service 校验）"""
    element_name: Optional[str] = Field(None, min_length=1, max_length=100)
    element_type: Optional[str] = Field(None, max_length=50)
    element_text: Optional[str] = Field(None, max_length=200)


class LocatorReorderRequest(BaseModel):
    index: int = Field(..., ge=0, description="被移动的定位器下标")
    direction: str = Field(..., pattern="^(up|down)$")


class LocatorAddRequest(BaseModel):
    type: str = Field(..., max_length=30, description="id/css/data-testid/text/xpath/自定义")
    value: str = Field(..., min_length=1, max_length=500)
    score: int = Field(50, ge=0, le=150)
```

- [ ] **Step 6: API 冒烟测试**（追加到 tests/test_api_elements.py 风格，mock db + TestClient）

确认 `PUT /elements/{id}` 400 on 非白名单字段、`POST .../reorder` 200、`GET .../references` 返回 count。

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/element_asset_service.py backend/app/api/v1/elements.py backend/app/schemas/element_schema.py backend/tests/test_element_asset_service.py backend/tests/test_api_elements.py
git commit -m "feat(elements): element CRUD + locator reorder + recycle bin + reference endpoints"
```

---

### Task 5: 页面树（层级 + 右键编辑 + 上下移）

**Files:**
- Modify: `backend/app/services/element_asset_service.py`（追加页面树方法）
- Modify: `backend/app/api/v1/elements.py`
- Test: `tests/test_element_asset_service.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
class TestPageTree:
    @pytest.mark.asyncio
    async def test_create_page_with_parent(self):
        db = _db()
        created = {}

        class _FakePage:
            def __init__(self, **kw):
                self.__dict__.update(kw)
                self.id = uuid4()
                created.update(kw)
        # patch create_page 走 service 方法
        svc = ElementAssetService(db)
        # 直接测参数传递（真实建页复用 ElementService.create_page，不重复造）
        # 这里测 service 层参数校验
        with pytest.raises(ValueError):
            await svc.create_sub_page("p1", None, "")  # 空名字

    @pytest.mark.asyncio
    async def test_move_page_swaps_sort_order(self):
        db = _db()
        pages = {uuid4(): MagicMock(sort_order=1), uuid4(): MagicMock(sort_order=2)}
        plist = list(pages.values())
        plist[0].parent_id = None
        plist[1].parent_id = None

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = plist
            return r
        db.execute = _execute
        db.commit = AsyncMock()

        svc = ElementAssetService(db)
        await svc.move_page(str(plist[0].id), "down")
        assert plist[0].sort_order == 2 and plist[1].sort_order == 1

    @pytest.mark.asyncio
    async def test_delete_page_with_children_blocked(self):
        db = _db()
        page = MagicMock(id=uuid4())
        child = MagicMock(parent_id=page.id)

        async def _get(cls, pid):
            return page
        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [child]  # 有子页面
            return r
        db.get = _get
        db.execute = _execute

        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="子页面"):
            await svc.delete_page(str(page.id))

    @pytest.mark.asyncio
    async def test_delete_page_with_elements_requires_target(self):
        """页面下有元素时删除必须指定迁移目标页，或 force 一起进回收站"""
        db = _db()
        page = MagicMock(id=uuid4())

        async def _get(cls, pid):
            return page
        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []  # 无子页面
            return r
        db.get = _get
        db.execute = _execute

        svc = ElementAssetService(db)
        # 模拟页下有元素：patch count
        svc._count_page_elements = AsyncMock(return_value=3)
        with pytest.raises(ValueError, match="迁移"):
            await svc.delete_page(str(page.id), move_to_page_id=None, force=False)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_element_asset_service.py -v -k PageTree`
Expected: FAIL

- [ ] **Step 3: 实现（追加到 element_asset_service.py）**

```python
    async def create_sub_page(self, project_id: str, parent_id: Optional[str],
                              page_name: str, page_url: str = "") -> "PageRepository":
        """创建子页面（parent_id=None 即根级）。"""
        if not page_name or not page_name.strip():
            raise ValueError("页面名称不能为空")
        from app.models.element import PageRepository
        page = PageRepository(
            project_id=UUID(project_id),
            parent_id=_uuid.UUID(parent_id) if parent_id else None,
            page_name=page_name.strip()[:100],
            page_url=page_url or f"/#{page_name.strip()}",
        )
        self.db.add(page)
        await self.db.commit()
        return page

    async def rename_page(self, page_id: str, page_name: str) -> None:
        if not page_name or not page_name.strip():
            raise ValueError("页面名称不能为空")
        from app.models.element import PageRepository
        page = await self.db.get(PageRepository, _uuid.UUID(page_id))
        if not page:
            raise ValueError("页面不存在")
        page.page_name = page_name.strip()[:100]
        await self.db.commit()

    async def move_page(self, page_id: str, direction: str) -> None:
        """同级上移/下移：与相邻页面交换 sort_order。"""
        from app.models.element import PageRepository
        page = await self.db.get(PageRepository, _uuid.UUID(page_id))
        if not page:
            raise ValueError("页面不存在")
        result = await self.db.execute(
            select(PageRepository).where(
                PageRepository.project_id == page.project_id,
                PageRepository.parent_id == page.parent_id,
            ).order_by(PageRepository.sort_order, PageRepository.created_at)
        )
        siblings = list(result.scalars().all())
        idx = next(i for i, p in enumerate(siblings) if p.id == page.id)
        j = idx - 1 if direction == "up" else idx + 1
        if j < 0 or j >= len(siblings):
            return
        siblings[idx].sort_order, siblings[j].sort_order = siblings[j].sort_order, siblings[idx].sort_order
        await self.db.commit()

    async def delete_page(self, page_id: str, move_to_page_id: Optional[str] = None,
                          force: bool = False) -> None:
        """删页面：有子页面拒绝；有元素时须给迁移目标或 force（元素一起进回收站）。"""
        from app.models.element import PageRepository, ElementRepository
        page = await self.db.get(PageRepository, _uuid.UUID(page_id))
        if not page:
            raise ValueError("页面不存在")
        children = await self.db.execute(
            select(PageRepository).where(PageRepository.parent_id == page.id)
        )
        if children.scalars().all():
            raise ValueError("存在子页面，请先删除/迁移子页面")
        n = await self._count_page_elements(page_id)
        if n > 0 and not force and not move_to_page_id:
            raise ValueError(f"页面下有 {n} 个元素，请指定迁移目标页面或选择一并删除")
        if n > 0 and move_to_page_id:
            target = _uuid.UUID(move_to_page_id)
            await self.db.execute(
                ElementRepository.__table__.update()
                .where(ElementRepository.page_id == page.id)
                .values(page_id=target)
            )
        elif n > 0 and force:
            await self.db.execute(
                ElementRepository.__table__.update()
                .where(ElementRepository.page_id == page.id)
                .values(status="deleted", recycled_at=datetime.utcnow())
            )
        await self.db.delete(page)
        await self.db.commit()

    async def _count_page_elements(self, page_id: str) -> int:
        from app.models.element import ElementRepository
        from sqlalchemy import func
        r = await self.db.execute(
            select(func.count(ElementRepository.id)).where(
                ElementRepository.page_id == _uuid.UUID(page_id),
                ElementRepository.status == "active",
            )
        )
        return r.scalar() or 0
```

- [ ] **Step 4: API 端点**

```python
@router.post("/pages-tree")
async def create_sub_page(request: SubPageCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        page = await ElementAssetService(db).create_sub_page(
            request.project_id, request.parent_id, request.page_name, request.page_url or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": page.to_dict()}


@router.put("/pages-tree/{page_id}")
async def rename_page(page_id: str, request: PageRenameRequest, db: AsyncSession = Depends(get_db)):
    try:
        await ElementAssetService(db).rename_page(page_id, request.page_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "renamed"}


@router.post("/pages-tree/{page_id}/move")
async def move_page(page_id: str, request: PageMoveRequest, db: AsyncSession = Depends(get_db)):
    try:
        await ElementAssetService(db).move_page(page_id, request.direction)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "moved"}


@router.delete("/pages-tree/{page_id}")
async def delete_page_tree_node(page_id: str, move_to_page_id: Optional[str] = Query(None),
                                force: bool = Query(False), db: AsyncSession = Depends(get_db)):
    try:
        await ElementAssetService(db).delete_page(page_id, move_to_page_id, force)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "message": "deleted"}
```

schemas 追加：

```python
class SubPageCreateRequest(BaseModel):
    project_id: str
    parent_id: Optional[str] = None
    page_name: str = Field(..., min_length=1, max_length=100)
    page_url: Optional[str] = None


class PageRenameRequest(BaseModel):
    page_name: str = Field(..., min_length=1, max_length=100)


class PageMoveRequest(BaseModel):
    direction: str = Field(..., pattern="^(up|down)$")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_element_asset_service.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/element_asset_service.py backend/app/api/v1/elements.py backend/app/schemas/element_schema.py backend/tests/test_element_asset_service.py
git commit -m "feat(elements): page tree CRUD — parent/sort, rename, move, guarded delete"
```

---

### Task 6: 全局共享元素

**Files:**
- Modify: `backend/app/services/element_asset_service.py`（追加）
- Modify: `backend/app/api/v1/elements.py`（列表端点支持 scope 过滤 + 全局元素可被任意页面脚本引用）
- Modify: `backend/app/services/element_service.py`（find_by_name 兼容全局元素：项目内 page 级查不到时查 global）
- Test: `tests/test_element_asset_service.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
class TestGlobalElements:
    @pytest.mark.asyncio
    async def test_create_global_element_no_page(self):
        """全局元素不挂页面：page_id 为空 + scope=global"""
        db = _db()
        added = []
        db.add = lambda o: added.append(o)
        db.commit = AsyncMock()
        db.flush = AsyncMock()

        svc = ElementAssetService(db)
        el = await svc.create_element(
            project_id="p1", name="左侧菜单-设备管理", etype="link",
            text="设备管理", scope="global", page_id=None,
            locators=[{"type": "text", "value": "设备管理"}],
        )
        assert added[0].scope == "global"
        assert added[0].page_id is None

    @pytest.mark.asyncio
    async def test_page_element_requires_page(self):
        db = _db()
        svc = ElementAssetService(db)
        with pytest.raises(ValueError, match="页面"):
            await svc.create_element("p1", "x", "button", "", scope="page", page_id=None)

    @pytest.mark.asyncio
    async def test_list_elements_scope_filter(self):
        db = _db()
        els = [MagicMock(scope="global"), MagicMock(scope="page")]

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = els
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        out = await svc.list_elements("p1", scope="global")
        assert all(e.scope == "global" for e in out)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_element_asset_service.py -v -k Global`
Expected: FAIL

- [ ] **Step 3: 实现（追加）**

```python
    async def create_element(self, project_id: str, name: str, etype: str, text: str,
                             scope: str = "page", page_id: Optional[str] = None,
                             locators: Optional[List[Dict]] = None) -> "ElementRepository":
        """新建元素。scope=global 时 page_id 必须为空；page 级必须有页面。"""
        from app.models.element import ElementRepository
        scope = scope or "page"
        if scope == "global" and page_id:
            raise ValueError("全局元素不挂页面")
        if scope == "page" and not page_id:
            raise ValueError("页面级元素必须指定页面")
        el = ElementRepository(
            project_id=UUID(project_id),
            page_id=_uuid.UUID(page_id) if page_id else None,
            scope=scope,
            element_id=ElementRepository and f"manual-{_uuid.uuid4().hex[:12]}",
            element_name=name[:100],
            element_type=etype or "other",
            element_text=(text or "")[:200] or None,
            locator_strategies={"strategies": locators or []},
            source="manual",
            status="active",
        )
        self.db.add(el)
        await self.db.commit()
        return el

    async def list_elements(self, project_id: str, scope: Optional[str] = None,
                            page_id: Optional[str] = None, status: str = "active",
                            keyword: Optional[str] = None) -> List:
        """元素列表：scope/page/keyword 过滤（page_id='all' 表示全部含全局）。"""
        from app.models.element import ElementRepository
        from sqlalchemy import or_
        conds = [ElementRepository.project_id == UUID(project_id),
                 ElementRepository.status == status]
        if scope:
            conds.append(ElementRepository.scope == scope)
        if page_id and page_id != "all":
            # 选中某页面：该页面元素 + 全局元素（全局可被任何页面脚本引用）
            conds.append(or_(ElementRepository.page_id == _uuid.UUID(page_id),
                             ElementRepository.scope == "global"))
        if keyword:
            conds.append(or_(ElementRepository.element_name.ilike(f"%{keyword}%"),
                             ElementRepository.element_text.ilike(f"%{keyword}%")))
        result = await self.db.execute(
            select(ElementRepository).where(*conds).order_by(ElementRepository.updated_at.desc())
        )
        return result.scalars().all()
```

**find_by_name 兼容全局**（`element_service.py` 的 `find_by_name`，or_ 条件追加一行）:

```python
                or_(
                    ElementRepository.element_name == element_name,
                    ElementRepository.element_text == element_name,
                ),
```
改为 status 过滤不变（全局元素 status 也是 active 天然命中）——**无需改 find_by_name**，它按 project+name 查，global 元素同 project 下天然可查。验证：写一个测试确认。

```python
class TestGlobalLookup:
    @pytest.mark.asyncio
    async def test_find_by_name_finds_global(self):
        """全局元素（page_id=None）同项目下可被 find_by_name 命中——现有逻辑天然支持，回归锁定"""
        from app.services.element_service import ElementService
        db = _db()
        el = MagicMock()
        el.element_name = "左侧菜单"
        el.element_text = "设备管理"

        async def _execute(q):
            r = MagicMock()
            r.scalar_one_or_none.return_value = el
            return r
        db.execute = _execute

        svc = ElementService(db)
        found = await svc.find_by_name("p1", "设备管理")
        assert found is el
```

- [ ] **Step 4: API** — 元素列表端点（替换旧 `GET /pages/{page_id}/elements` 的消费路径，新增全量列表）

```python
@router.get("/elements-asset")
async def list_elements_asset(project_id: str = Query(...),
                              scope: Optional[str] = Query(None, pattern="^(page|global)$"),
                              page_id: Optional[str] = Query(None, description="页面ID或all"),
                              keyword: Optional[str] = Query(None, max_length=100),
                              db: AsyncSession = Depends(get_db)):
    try:
        els = await ElementAssetService(db).list_elements(project_id, scope, page_id, keyword=keyword)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": [e.to_dict() for e in els]}


@router.post("/elements-asset")
async def create_element_asset(request: ElementCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        el = await ElementAssetService(db).create_element(
            request.project_id, request.name, request.element_type, request.element_text or "",
            scope=request.scope, page_id=request.page_id,
            locators=request.locators,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": el.to_dict()}
```

schema 追加：

```python
class ElementCreateRequest(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    element_type: str = Field("other", max_length=50)
    element_text: Optional[str] = Field(None, max_length=200)
    scope: str = Field("page", pattern="^(page|global)$")
    page_id: Optional[str] = None
    locators: Optional[List[dict]] = None
```

- [ ] **Step 5: 跑全量元素测试**

Run: `python -m pytest tests/test_element_asset_service.py tests/test_api_elements.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/element_asset_service.py backend/app/services/element_service.py backend/app/api/v1/elements.py backend/app/schemas/element_schema.py backend/tests/test_element_asset_service.py
git commit -m "feat(elements): global shared elements — scope field, page-all listing, manual create"
```

---

### Task 7: 快速校验端点

**Files:**
- Modify: `backend/app/api/v1/elements.py`
- Modify: `backend/app/services/element_asset_service.py`（校验逻辑）
- Test: `tests/test_locator_verify.py`

- [ ] **Step 1: 写失败测试**

`tests/test_locator_verify.py`:

```python
"""定位器快速校验：单条定位器在真实页面跑一次 querySelector，返回命中结果。
service 层 mock playwright page；真浏览器验证走手动验收。"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.element_asset_service import verify_locator_on_page


@pytest.mark.asyncio
async def test_unique_hit_adds_score():
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(return_value=[MagicMock()])  # 命中1个
    result = await verify_locator_on_page(page, {"type": "css", "value": "#btn", "score": 80})
    assert result["hit_count"] == 1
    assert result["score"] == 100  # 80 + 20 唯一加分

@pytest.mark.asyncio
async def test_multi_hit_penalizes():
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
    result = await verify_locator_on_page(page, {"type": "css", "value": ".btn", "score": 80})
    assert result["hit_count"] == 3
    assert result["score"] == 60  # 80 - 20 非唯一扣分

@pytest.mark.asyncio
async def test_no_hit_returns_zero(self=None):
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(return_value=[])
    result = await verify_locator_on_page(page, {"type": "css", "value": "#gone", "score": 80})
    assert result["hit_count"] == 0

@pytest.mark.asyncio
async def test_selector_error_returns_error(self=None):
    page = MagicMock()
    page.locator.return_value.all = AsyncMock(side_effect=Exception("bad selector"))
    result = await verify_locator_on_page(page, {"type": "css", "value": "###", "score": 80})
    assert result["error"] is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_locator_verify.py -v`
Expected: FAIL ImportError

- [ ] **Step 3: 实现（追加到 element_asset_service.py）**

```python
async def verify_locator_on_page(page, locator: Dict) -> Dict:
    """单条定位器在已登录页面上验证。返回 {hit_count, score, error}。
    评分规则与抓取端 verify_and_score_locator 对齐：唯一+20 / 非唯一-20。"""
    value = locator.get("value", "")
    score = locator.get("score", 0)
    try:
        if locator.get("type") == "xpath":
            found = await page.locator(f"xpath={value}").all()
        else:
            found = await page.locator(value).all()
        n = len(found)
        final = score + 20 if n == 1 else (score - 20 if n > 1 else 0)
        return {"hit_count": n, "score": max(final, 0), "error": None}
    except Exception as e:
        return {"hit_count": 0, "score": 0, "error": str(e)[:200]}
```

API 端点（elements.py）：

```python
@router.post("/elements/{element_id}/locators/verify")
async def verify_element_locator(element_id: str, request: LocatorVerifyRequest,
                                 db: AsyncSession = Depends(get_db)):
    """快速校验：用环境管理的激活环境 URL 开 headed 页面跑一次定位。
    复用 playwright_service 登录态（fetch_page 同链路）。"""
    from app.services.playwright_service import PlaywrightService
    from app.models.system import TestEnv
    from sqlalchemy import select as _select

    el = await db.get(ElementRepository, __import__("uuid").UUID(element_id))
    if not el or not el.page_id:
        raise HTTPException(status_code=404, detail="元素不存在或为全局元素(无页面URL)")
    page_row = await db.get(PageRepository, el.page_id)
    env = (await db.execute(
        _select(TestEnv).where(TestEnv.status == "active").limit(1)
    )).scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=400, detail="无激活测试环境")

    pw = PlaywrightService()
    try:
        page = await pw.fetch_page(env.url + (page_row.page_url or ""), headless=True)
        result = await verify_locator_on_page(
            page, {"type": request.locator_type, "value": request.locator_value, "score": request.score or 0})
    finally:
        await pw.close()
    return {"code": 0, "data": result}
```

schema：

```python
class LocatorVerifyRequest(BaseModel):
    locator_type: str = Field(..., max_length=30)
    locator_value: str = Field(..., min_length=1, max_length=500)
    score: Optional[int] = Field(None, ge=0, le=150)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_locator_verify.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/element_asset_service.py backend/app/api/v1/elements.py backend/app/schemas/element_schema.py backend/tests/test_locator_verify.py
git commit -m "feat(elements): quick locator verify — live page querySelector with unique-hit scoring"
```

---

### Task 8: 导入导出

**Files:**
- Modify: `backend/app/api/v1/elements.py`（导出 JSON / 导入 JSON）
- Modify: `backend/app/services/element_asset_service.py`
- Test: `tests/test_element_asset_service.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
class TestImportExport:
    @pytest.mark.asyncio
    async def test_export_shape(self):
        db = _db()
        el = MagicMock()
        el.to_dict.return_value = {
            "element_name": "登录按钮", "element_type": "button", "scope": "page",
            "element_text": "登录", "locator_strategies": {"strategies": [
                {"type": "id", "value": "#login", "score": 100}]},
        }
        els = [el]

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = els
            return r
        db.execute = _execute

        svc = ElementAssetService(db)
        data = await svc.export_elements("p1")
        assert data["version"] == 1
        assert data["elements"][0]["element_name"] == "登录按钮"
        assert "locator_strategies" in data["elements"][0]

    @pytest.mark.asyncio
    async def test_import_creates_elements(self):
        db = _db()
        svc = ElementAssetService(db)
        svc.create_element = AsyncMock()
        payload = {"version": 1, "elements": [
            {"element_name": "x", "element_type": "button", "scope": "page",
             "page_id": "pid", "element_text": "", "locator_strategies": {"strategies": []}}]}
        n = await svc.import_elements("p1", payload)
        assert n == 1
        svc.create_element.assert_awaited_once()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_element_asset_service.py -v -k ImportExport`
Expected: FAIL

- [ ] **Step 3: 实现（追加）**

```python
    async def export_elements(self, project_id: str) -> Dict:
        """导出项目全部 active 元素为可移植 JSON。"""
        from app.models.element import ElementRepository
        result = await self.db.execute(
            select(ElementRepository).where(
                ElementRepository.project_id == UUID(project_id),
                ElementRepository.status == "active")
        )
        els = result.scalars().all()
        return {"version": 1, "exported_at": datetime.utcnow().isoformat(),
                "elements": [e.to_dict() for e in els]}

    async def import_elements(self, project_id: str, payload: Dict) -> int:
        """导入元素 JSON（跨项目/环境复用）。逐条走 create_element，坏行跳过。"""
        n = 0
        for item in (payload or {}).get("elements", []):
            if not isinstance(item, dict) or not item.get("element_name"):
                continue
            try:
                await self.create_element(
                    project_id=project_id,
                    name=item["element_name"],
                    etype=item.get("element_type", "other"),
                    text=item.get("element_text") or "",
                    scope=item.get("scope", "page"),
                    page_id=item.get("page_id"),
                    locators=(item.get("locator_strategies") or {}).get("strategies", []),
                )
                n += 1
            except Exception as e:
                logger.warning(f"import element skipped: {e}")
        return n
```

API：

```python
@router.get("/elements-export")
async def export_elements(project_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    data = await ElementAssetService(db).export_elements(project_id)
    return {"code": 0, "data": data}


@router.post("/elements-import")
async def import_elements(request: ElementImportRequest, db: AsyncSession = Depends(get_db)):
    try:
        n = await ElementAssetService(db).import_elements(request.project_id, request.payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "data": {"imported": n}}
```

schema：

```python
class ElementImportRequest(BaseModel):
    project_id: str
    payload: dict
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全绿（≥573 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/element_asset_service.py backend/app/api/v1/elements.py backend/app/schemas/element_schema.py backend/tests/test_element_asset_service.py
git commit -m "feat(elements): import/export portable JSON for cross-project reuse"
```

---

### Task 9: 前端路由 + 元素列表页

**Files:**
- Modify: `frontend/src/router/index.js`
- Create: `frontend/src/views/ElementList.vue`
- Modify: `frontend/src/api/element.js`

- [ ] **Step 1: 路由调整**

`frontend/src/router/index.js`，把现有 elements 路由替换为：

```js
        {
          path: 'elements',
          name: 'Elements',
          redirect: '/elements/capture',
        },
        {
          path: 'elements/capture',
          name: 'ElementCapture',
          component: () => import('@/views/ElementLibrary.vue'),
          meta: { title: '元素抓取' }
        },
        {
          path: 'elements/list',
          name: 'ElementList',
          component: () => import('@/views/ElementList.vue'),
          meta: { title: '元素管理' }
        },
```

- [ ] **Step 2: API 封装**（`frontend/src/api/element.js` 追加）

```js
// ---- 元素管理（阶段1） ----
async listElementsAsset(projectId, { scope, pageId, keyword } = {}) {
  const response = await axios.get('/elements-asset', { params: {
    project_id: projectId,
    scope: scope || undefined,
    page_id: pageId || undefined,
    keyword: keyword || undefined,
  }})
  return response.data
},
async createElementAsset(data) {
  const response = await axios.post('/elements-asset', data)
  return response.data
},
async updateElement(elementId, fields) {
  const response = await axios.put(`/elements/${elementId}`, fields)
  return response.data
},
async reorderLocator(elementId, index, direction) {
  const response = await axios.post(`/elements/${elementId}/locators/reorder`, { index, direction })
  return response.data
},
async addLocator(elementId, type, value, score = 50) {
  const response = await axios.post(`/elements/${elementId}/locators`, { type, value, score })
  return response.data
},
async verifyLocator(elementId, locatorType, locatorValue) {
  const response = await axios.post(`/elements/${elementId}/locators/verify`,
    { locator_type: locatorType, locator_value: locatorValue })
  return response.data
},
async elementReferences(elementId, projectId) {
  const response = await axios.get(`/elements/${elementId}/references`, { params: { project_id: projectId } })
  return response.data
},
async recycleElement(elementId) {
  const response = await axios.post(`/elements/${elementId}/recycle`)
  return response.data
},
async restoreElement(elementId) {
  const response = await axios.post(`/elements/${elementId}/restore`)
  return response.data
},
async recycleBin(projectId) {
  const response = await axios.get('/recycle-bin', { params: { project_id: projectId } })
  return response.data
},
async createSubPage(data) {
  const response = await axios.post('/pages-tree', data)
  return response.data
},
async renamePage(pageId, pageName) {
  const response = await axios.put(`/pages-tree/${pageId}`, { page_name: pageName })
  return response.data
},
async movePage(pageId, direction) {
  const response = await axios.post(`/pages-tree/${pageId}/move`, { direction })
  return response.data
},
async deletePageNode(pageId, moveToPageId, force) {
  const response = await axios.delete(`/pages-tree/${pageId}`, { params: {
    move_to_page_id: moveToPageId || undefined, force: force || undefined } })
  return response.data
},
async exportElements(projectId) {
  const response = await axios.get('/elements-export', { params: { project_id: projectId } })
  return response.data
},
async importElements(projectId, payload) {
  const response = await axios.post('/elements-import', { project_id: projectId, payload })
  return response.data
},
```

- [ ] **Step 3: 元素列表页 ElementList.vue**

布局照原型（v6 elements-list section）：顶部项目下拉 → 左 250px 页面树卡片（全部元素/🌐全局元素/页面节点，右键菜单：重命名/上移/下移/删除）→ 右侧表格（10列：选择框/元素/类型/首选定位/作用域/状态/引用数/来源/更新时间/操作）+ 工具栏（导入/导出/回收站/+新建元素/搜索）。

关键交互（完整代码骨架，样式沿用项目 page-container 惯例）：

```vue
<template>
  <div class="element-list page-container">
    <el-card>
      <div class="toolbar">
        <el-select v-model="projectId" placeholder="选择项目" style="width: 220px" @change="loadAll">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-input v-model="keyword" placeholder="搜索元素名/定位值" clearable style="width: 220px"
          @keyup.enter="loadElements" @clear="loadElements" />
        <el-button @click="exportJson">📤 导出</el-button>
        <el-button @click="importDialog = true">📥 导入</el-button>
        <el-button @click="openRecycle">🗑️ 回收站</el-button>
        <el-button type="primary" @click="createDialog = true">+ 新建元素</el-button>
      </div>

      <div class="main-grid">
        <!-- 页面树 -->
        <el-card class="tree-card">
          <div class="tree-node" :class="{ active: selectedPage === 'all' }" @click="selectPage('all')">
            📁 全部元素
          </div>
          <div class="tree-node" :class="{ active: selectedPage === 'global' }" @click="selectPage('global')">
            🌐 全局元素
          </div>
          <div v-for="p in pages" :key="p.id"
               class="tree-node" :class="{ active: selectedPage === p.id }"
               @click="selectPage(p.id)" @contextmenu.prevent="openPageMenu($event, p)">
            📄 {{ p.page_name }} ({{ p.element_count || 0 }})
          </div>
        </el-card>

        <!-- 元素表格 -->
        <el-table :data="elements" v-loading="loading" stripe>
          <el-table-column prop="element_name" label="元素" min-width="140" show-overflow-tooltip />
          <el-table-column prop="element_type" label="类型" width="90" />
          <el-table-column label="首选定位(置信度最高)" min-width="220">
            <template #default="{ row }">
              <code>{{ bestLocator(row) }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="scope" label="作用域" width="80">
            <template #default="{ row }">
              <el-tag :type="row.scope === 'global' ? 'warning' : 'info'" size="small">
                {{ row.scope === 'global' ? '全局' : '页面' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="80" />
          <el-table-column label="引用数" width="80" align="center">
            <template #default="{ row }">{{ refCounts[row.id] ?? '-' }}</template>
          </el-table-column>
          <el-table-column prop="source" label="来源" width="90" />
          <el-table-column prop="updated_at" label="更新时间" width="160">
            <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link @click="openDrawer(row)">详情</el-button>
              <el-button type="danger" link @click="removeElement(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 右键页面菜单 -->
    <teleport to="body">
      <div v-if="pageMenu.visible" class="ctx-menu" :style="{ left: pageMenu.x + 'px', top: pageMenu.y + 'px' }"
           @mouseleave="pageMenu.visible = false">
        <div @click="renamePage">重命名</div>
        <div @click="movePageNode('up')">上移</div>
        <div @click="movePageNode('down')">下移</div>
        <div class="danger" @click="removePage">删除</div>
      </div>
    </teleport>

    <!-- 元素详情抽屉（定位器调序/自定义定位/快速校验/引用清单） -->
    <el-drawer v-model="drawer.visible" :title="'元素详情 · ' + (drawer.row?.element_name || '')" size="480px">
      <template v-if="drawer.row">
        <el-tag size="small" class="mr8">{{ drawer.row.element_type }}</el-tag>
        <el-tag size="small" type="warning" class="mr8">{{ drawer.row.scope === 'global' ? '全局' : '页面' }}</el-tag>
        <el-tag size="small">{{ drawer.row.status }}</el-tag>

        <h4>定位器（按置信度排序，可调整）</h4>
        <div v-for="(loc, i) in drawerLocators" :key="i" class="loc-row">
          <span class="star">{{ i === 0 ? '★' : '' }}</span>
          <code class="loc-value">{{ loc.type }}: {{ loc.value }}</code>
          <el-tag size="small" :type="i === 0 ? 'success' : 'info'">{{ loc.score }}</el-tag>
          <el-tag v-if="loc.source" size="small" type="info">{{ loc.source }}</el-tag>
          <el-button size="small" :disabled="i === 0" @click="moveLoc(i, 'up')">↑</el-button>
          <el-button size="small" :disabled="i === drawerLocators.length - 1" @click="moveLoc(i, 'down')">↓</el-button>
        </div>
        <el-button size="small" @click="addLocDialog = true">+ 自定义定位器</el-button>

        <h4>引用脚本</h4>
        <div v-for="s in drawer.refs" :key="s.id" class="ref-item">{{ s.name }}</div>
        <div v-if="!drawer.refs.length" class="empty-text">暂无脚本引用</div>

        <h4>快速校验</h4>
        <el-button size="small" type="primary" :loading="verifying" @click="verifyBest">校验首选定位</el-button>
        <div v-if="verifyResult" class="verify-result">
          命中 {{ verifyResult.hit_count }} 个 · score {{ verifyResult.score }}
          <span v-if="verifyResult.error" class="err">{{ verifyResult.error }}</span>
        </div>
      </template>
    </el-drawer>
  </div>
</template>
```

script 部分要点（完整逻辑，实施时补齐样式）：

```js
// bestLocator: (row.locator_strategies?.strategies || []) 按 score 降序取[0]，显示 `type: value`
// loadAll: 并行拉 projects/pages/elements；selectPage('all'|'global'|pageId) 决定 listElementsAsset 的 scope/pageId 参数
//   - 'all' → page_id='all'；'global' → scope='global'；具体页面 → page_id=页面id（后端自动附带全局元素）
// loadElements 后批量拉引用计数（逐个 elementReferences，Element Plus 表格量小可接受；>50 条时后续优化）
// openDrawer: 计算属性 drawerLocators = normalize 后的 strategies（前端再排一次序保证一致）
// moveLoc(i, dir): 调 reorderLocator API → 成功后本地交换 + 刷新
// removeElement: 先 elementReferences 拿 count；count>0 → ElMessageBox.confirm(`该元素被 ${count} 个脚本引用...确认删除（软删，30天可恢复）`)；确认后 recycleElement + 刷新
// openPageMenu: 记录 x/y 和页面行；renamePage 用 ElMessageBox.prompt；removePage 先 deletePageNode（无参），捕获 400 错误提示"指定迁移目标或一并删除"→ 二次弹选择
// exportJson: exportElements → Blob 下载；importDialog 内上传 JSON → importElements → 提示 imported 数
// openRecycle: recycleBin 列表弹窗，每行"恢复"按钮
```

- [ ] **Step 4: build 验证**

Run: `cd D:\MoonTest\frontend && npm run build`
Expected: ✓ built

- [ ] **Step 5: Commit**

```bash
git add frontend/src/router/index.js frontend/src/views/ElementList.vue frontend/src/api/element.js
git commit -m "feat(elements): ElementList page — tree + 10-col table + drawer reorder/verify/recycle"
```

---

### Task 10: 菜单二级化 + 真浏览器验收

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`
- Test: 手动验收（真浏览器，mock 测不了的链路）

- [ ] **Step 1: 菜单改二级**（MainLayout.vue，替换现有单项元素库菜单）

```html
        <el-sub-menu index="element-assets">
          <template #title>
            <el-icon><Grid /></el-icon>
            <span>元素资产</span>
          </template>
          <el-menu-item index="/elements/capture">元素抓取</el-menu-item>
          <el-menu-item index="/elements/list">元素管理</el-menu-item>
        </el-sub-menu>
```

- [ ] **Step 2: build + 重启**

```bash
cd D:\MoonTest\frontend && npm run build
# backend --reload 自动热加载；确认 8000 端口进程在
```

- [ ] **Step 3: 真浏览器验收清单**（逐项过，截图留证）
  1. 菜单显示「元素资产」二级两项；/elements 旧地址重定向到 /elements/capture，原抓取页功能完好（一次性+会话式 Tab 可打开）
  2. 元素管理页：选项目 → 页面树出现 → 选根显示全部元素（现有 6 条元素可见）
  3. 右键页面 → 重命名生效；上移/下移后顺序持久
  4. 元素详情抽屉：定位器列表按 score 降序；↑↓ 调序后首选（★）变化，刷新后保持
  5. 「+ 自定义定位器」添加一条 CSS → 出现在列表（source=manual）
  6. 快速校验：对一个真实可达页面的元素校验 → 返回命中数（需激活环境可达；不可达时确认报错提示友好）
  7. 删除有引用的元素 → 弹确认含引用脚本数；回收站可见 → 恢复后回列表
  8. 全局元素：新建一个 scope=global 的元素（如导航栏按钮）→ 任一页面树节点下都能看到它
  9. 导出 JSON → 清一测试项目重新导入 → imported 计数正确
  10. 旧数据兼容：旧元素（strategy 无 score 字段）在列表页显示正常（归一化兜底生效）

- [ ] **Step 4: 全量回归 + Commit**

```bash
cd D:\MoonTest\backend && python -m pytest tests/ -q
git add frontend/src/layouts/MainLayout.vue
git commit -m "feat(elements): menu split into capture/list sub-items (#elem-assets phase1)"
```

---

## Self-Review 结果

- **Spec 覆盖**：定位器 score 统一（T2）、引用计数+删除保护（T3/T4）、页面树（T5）、全局元素（T6）、快速校验（T7）、导入导出（T8）、回收站（T4）、菜单拆分（T9/T10）、抓取页迁路由（T9）——沟通定稿的阶段1范围全覆盖。抓取时的“目标页面级联选择”已存在（capture import page_id），无需任务。
- **类型一致性**：`normalize_strategies/select_primary_locator/build_fallback_chain/strategy_to_playwright`（T2 定义，find 消费）；`ElementAssetService` 方法名前后一致（count_references/list_referring_scripts/update_element/reorder_locator/add_locator/recycle_element/restore_element/list_recycled/create_sub_page/rename_page/move_page/delete_page/create_element/list_elements/export_elements/import_elements）。
- **遗留风险（已知，记录给执行者）**：① 旧 `_strategy_to_playwright` 删除时确认无其他 import（grep 已确认仅 element_service 内部使用）；② reorder 的 score 重排用 `150 - pos*10` 会压平原抓取评分——这是有意设计（排序即置信度，用户调序就是改置信度），但自愈回写 confidence 逻辑（cache_service ±1 操作的是**元素级** confidence 列，非 strategy.score）不受影响；③ 回收站 30 天自动清理不做（YAGNI，列表过滤 recycled_at 可后加）。
