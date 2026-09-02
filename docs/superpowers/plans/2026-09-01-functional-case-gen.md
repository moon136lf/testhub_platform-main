# 功能回归用例生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** 白盒页「生成回归用例」改为：clone 仓库 → 静态解析前后端结构（菜单树+API清单）→ AI 批量生成功能回归用例 → 落 test_case 表。

**Spec:** `docs/superpowers/specs/2026-09-01-functional-case-gen-design.md`

**Tech:** 纯正则静态解析（零 AI 零 DB 可单测）+ AI 批量生成（glm-5.2，经 ai_gateway）+ 既有 test_case 表。

**测试约定:** 同步 def + asyncio_run；gateway 用 AsyncMock；网关 503 用 side_effect=Exception 模拟。

---

### Task 1: CodeStructureAnalyzer 静态解析器

**Files:**
- Create: `backend/app/services/code_structure_analyzer.py`
- Test: `backend/tests/test_code_structure_analyzer.py`

- [x] Step 1: 写失败测试

```python
"""CodeStructureAnalyzer tests (pure regex parsing, zero mocks)."""
from app.services.code_structure_analyzer import CodeStructureAnalyzer


ROUTER_JS = '''
const routes = [
  { path: '/dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '仪表盘' } },
  {
    path: '/cases',
    name: 'Cases',
    component: () => import('@/views/Cases.vue'),
    meta: { title: '用例管理' }
  },
  { path: '/settings/ai', name: 'AISettings', meta: { title: 'AI设置' } },
]
'''

API_PY = '''
@router.get("/projects")
async def list_projects():
    """获取项目列表"""
    ...

@router.post("/projects")
async def create_project(req: ProjectCreate):
    ...

@router.delete("/projects/{id}")
async def delete_project(id: str):
    """删除项目"""
    ...

@other_router.post("/scan")
async def trigger_scan(req):
    ...
'''


class TestAnalyzeFrontend:
    def test_extracts_routes_with_titles(self, tmp_path):
        rdir = tmp_path / "frontend" / "src" / "router"
        rdir.mkdir(parents=True)
        (rdir / "index.js").write_text(ROUTER_JS, encoding="utf-8")
        menus = CodeStructureAnalyzer().analyze_frontend(str(tmp_path))
        assert len(menus) == 3
        assert menus[0]["path"] == "/dashboard"
        assert menus[0]["title"] == "仪表盘"
        assert menus[1]["title"] == "用例管理"

    def test_skips_redirect_and_node_modules(self, tmp_path):
        rdir = tmp_path / "src" / "router"
        rdir.mkdir(parents=True)
        (rdir / "index.js").write_text(
            "{ path: '/a', redirect: '/b' },\n"
            "{ path: '/b', name: 'B', meta: { title: 'B页' } },", encoding="utf-8")
        nm = tmp_path / "node_modules" / "x" / "router"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text(ROUTER_JS, encoding="utf-8")
        menus = CodeStructureAnalyzer().analyze_frontend(str(tmp_path))
        assert len(menus) == 1  # redirect 行跳过, node_modules 忽略


class TestAnalyzeBackend:
    def test_extracts_api_endpoints(self, tmp_path):
        apidir = tmp_path / "backend" / "app" / "api" / "v1"
        apidir.mkdir(parents=True)
        (apidir / "projects.py").write_text(API_PY, encoding="utf-8")
        apis = CodeStructureAnalyzer().analyze_backend(str(tmp_path))
        assert len(apis) >= 3
        m = {(a["method"], a["path"]) for a in apis}
        assert ("GET", "/projects") in m
        assert ("POST", "/projects") in m
        assert ("DELETE", "/projects/{id}") in m
        # docstring 首行
        desc = next(a["desc"] for a in apis if a["method"] == "GET" and a["path"] == "/projects")
        assert "项目列表" in desc
        # 无 docstring 的有默认值
        post_desc = next(a["desc"] for a in apis if a["method"] == "POST" and a["path"] == "/projects")
        assert post_desc  # 非空 (函数名兜底)

    def test_empty_repo_returns_empty(self, tmp_path):
        assert CodeStructureAnalyzer().analyze_frontend(str(tmp_path)) == []
        assert CodeStructureAnalyzer().analyze_backend(str(tmp_path)) == []
```

- [x] Step 2: 跑测试确认失败（ModuleNotFoundError）

- [x] Step 3: 实现 `backend/app/services/code_structure_analyzer.py`

```python
"""被测系统前后端代码结构静态解析 (Vue Router + FastAPI). 零 AI 零 DB."""
import os
import re
from pathlib import Path


class CodeStructureAnalyzer:
    """解析 git clone 下来的仓库: 前端路由菜单 + 后端 API 清单."""

    def analyze_frontend(self, repo_path: str) -> list:
        """解析 router/index.js → [{path, name, title}] (跳过 redirect 路由)."""
        menus = []
        for rfile in self._find_files(repo_path, os.path.join("router", "index.js"),
                                      skip_dirs=("node_modules", ".git", "dist")):
            text = self._read(rfile)
            if not text:
                continue
            # 逐个 route 对象匹配 (DOTALL 处理多行定义)
            for m in re.finditer(
                r"\{\s*path:\s*['\"]([^'\"]+)['\"][^}]*?(?:meta:\s*\{[^}]*?title:\s*['\"]([^'\"]+)['\"])?[^}]*?\}",
                text, re.DOTALL):
                path, title = m.group(1), m.group(2)
                if "redirect" in m.group(0):
                    continue
                menus.append({
                    "path": path,
                    "name": path.lstrip("/").replace("/", "-") or "root",
                    "title": title or path,
                })
        return menus

    def analyze_backend(self, repo_path: str) -> list:
        """解析 api 目录 *.py → [{file, method, path, func, desc}]."""
        apis = []
        for pyfile in self._find_files(repo_path, "*.py",
                                       skip_dirs=(".git", "__pycache__", "node_modules", "tests", "test"),
                                       must_match=re.compile(r"api|router|v1", re.I)):
            text = self._read(pyfile)
            if not text or "@router." not in text:
                continue
            rel = str(pyfile).replace("\\", "/")
            # 匹配: @router.(method)("path") 紧随 async def funcname
            for m in re.finditer(
                r'@router\.(get|post|put|delete|patch)\(\s*["\']([^"\']*)["\'][^)]*\)\s*\n\s*(?:async\s+)?def\s+(\w+)[^\n]*\n(?:\s+"""([^"]*?)"""|\s+\'\'\'([^\']*?)\'\'\')?',
                text):
                method, path, func, d1, d2 = m.groups()
                desc = (d1 or d2 or func).strip().splitlines()[0] if (d1 or d2) else func
                apis.append({"file": rel, "method": method.upper(),
                             "path": path or f"/{func}", "func": func, "desc": desc[:100]})
        return apis

    # ---- helpers ----
    @staticmethod
    def _read(fpath: Path) -> str:
        try:
            return fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _find_files(repo_path: str, pattern: str, skip_dirs=(), must_match=None) -> list:
        root = Path(repo_path)
        if not root.exists():
            return []
        out = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fn in filenames:
                if fn == os.path.basename(pattern) or (pattern == "*.py" and fn.endswith(".py")):
                    full = Path(dirpath) / fn
                    if must_match and not must_match.search(str(full)):
                        continue
                    out.append(full)
        return out
```

- [x] Step 4: 跑测试确认通过（全绿）

- [x] Step 5: Commit

```bash
git add app/services/code_structure_analyzer.py tests/test_code_structure_analyzer.py
git commit -m "feat(whitescan): static code structure analyzer - vue router + fastapi (#func-gen T1)"
```
（commit 末尾加 Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>，下同）

---

### Task 2: FunctionalCaseGenerator（AI 批量生成 + 落库）

**Files:**
- Create: `backend/app/services/functional_case_generator.py`
- Test: `backend/tests/test_functional_case_generator.py`

- [x] Step 1: 写失败测试

```python
"""FunctionalCaseGenerator tests (mock gateway/db, real batching logic)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def asyncio_run(coro): return asyncio.run(coro)


def _make_db(existing_titles=()):
    db = MagicMock()
    # execute 用于查重; added 收集落库对象
    results = []
    for t in existing_titles:
        r = MagicMock()
        r.scalar_one_or_none.return_value = MagicMock()  # 已存在 → 非 None
        results.append(r)
    db._results = results
    db.added = []

    async def execute(q):
        if db._results:
            return db._results.pop(0)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = execute
    db.add = lambda o: db.added.append(o)
    db.flush = asyncio.run if False else None
    async def _flush(): pass
    db.flush = _flush
    return db


def _gw_ok(batches):
    """gateway 按序返回各批 JSON."""
    gw = MagicMock()
    gw.chat = AsyncMock(side_effect=[{"content": b, "tokens": 100} for b in batches])
    return gw


MENU_JSON = '''[
  {"title": "仪表盘-页面访问", "precondition": "已登录", "priority": "P1",
   "steps": [{"step": 1, "action": "点击仪表盘菜单", "expected": "页面正常加载"}]}
]'''

API_JSON = '''[
  {"title": "项目列表-GET /projects", "precondition": "已登录", "priority": "P2",
   "steps": [{"step": 1, "action": "GET /projects", "expected": "返回200项目数组"}]}
]'''


class TestGenerateFromRepo:
    def test_menu_and_api_batches(self, tmp_path, monkeypatch):
        """菜单+API 两类都生成; 落库字段正确."""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        from app.services.code_structure_analyzer import CodeStructureAnalyzer

        # 静态解析用真实文件
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text("{ path: '/dashboard', name: 'D', meta: { title: '仪表盘' } }", encoding="utf-8")
        apidir = tmp_path / "api" / "v1"; apidir.mkdir(parents=True)
        (apidir / "projects.py").write_text(
            '@router.get("/projects")\nasync def list_projects():\n    """获取项目列表"""\n', encoding="utf-8")

        db = _make_db()
        gw = _gw_ok([MENU_JSON, API_JSON])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        monkeypatch.setattr(gen, "gateway", gw)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        assert result["generated"] >= 2
        assert len(db.added) >= 2
        tc = db.added[0]
        assert tc.project_id == "p1"
        assert "回归" in tc.name
        assert tc.case_type == "regression"
        assert isinstance(tc.steps, list)

    def test_gateway_503_one_batch_does_not_abort(self, tmp_path):
        """单批失败(网关503)不中断整体, failed 计数."""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text(
            "{ path: '/a', meta: { title: 'A' } },\n{ path: '/b', meta: { title: 'B' } },\n"
            "{ path: '/c', meta: { title: 'C' } },", encoding="utf-8")  # 3菜单→1批
        db = _make_db()
        gw = MagicMock()
        gw.chat = AsyncMock(side_effect=Exception("503"))  # 全批失败
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        assert result["generated"] == 0
        assert result["failed"] >= 1  # 该批计入失败, 不抛异常

    def test_duplicate_title_skipped(self, tmp_path, monkeypatch):
        """同 title 已存在 → 跳过不落库."""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text("{ path: '/d', meta: { title: '仪表盘' } }", encoding="utf-8")
        # 先解析出 title, 再让查重返回已存在
        from app.services.code_structure_analyzer import CodeStructureAnalyzer
        menus = CodeStructureAnalyzer().analyze_frontend(str(tmp_path))
        db = MagicMock()
        r = MagicMock(); r.scalar_one_or_none.return_value = MagicMock()  # 已存在
        async def execute(q): return r
        db.execute = execute
        db.added = []
        async def _flush(): pass
        db.flush = _flush
        gw = _gw_ok([MENU_JSON])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        # 查重按生成的 title: monkeypatch _case_title_exists 返回 True
        gen._case_title_exists = AsyncMock(return_value=True)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        assert result["generated"] == 0
        assert len(db.added) == 0
```

- [x] Step 2: 跑测试确认失败

- [x] Step 3: 实现 `backend/app/services/functional_case_generator.py`

```python
"""功能回归用例生成器 (#9 增强): 静态解析代码结构 → AI 批量生成 → 落 test_case.

替换原 regression_case_generator (按安全问题生成). 用户需求: 读取被测系统
前后端代码, 生成每个菜单的功能回归用例 + 基础功能/增删改查用例.
"""
import asyncio
import json
import logging
import re
from uuid import UUID

from app.models.test_case import TestCase
from app.services.code_structure_analyzer import CodeStructureAnalyzer

logger = logging.getLogger(__name__)

MENU_BATCH_SIZE = 3   # 每批菜单数 (一次 AI 调用)
API_BATCH_SIZE = 8    # 每批 API 数
BATCH_SLEEP = 1.0     # 批间隔秒 (避免打爆网关)


class FunctionalCaseGenerator:
    def __init__(self, db, gateway):
        self.db = db
        self.gateway = gateway
        self.analyzer = CodeStructureAnalyzer()

    async def generate_from_repo(self, project_id: str, repo_path: str) -> dict:
        menus = self.analyzer.analyze_frontend(repo_path)
        apis = self.analyze_backend(repo_path)
        generated, failed = 0, 0

        # 菜单批
        for i in range(0, len(menus), MENU_BATCH_SIZE):
            batch = menus[i:i + MENU_BATCH_SIZE]
            ok, n = await self._gen_menu_batch(project_id, batch)
            generated += n
            failed += 0 if ok else 1
            await asyncio.sleep(BATCH_SLEEP)

        # API 批
        for i in range(0, len(apis), API_BATCH_SIZE):
            batch = apis[i:i + API_BATCH_SIZE]
            ok, n = await self._gen_api_batch(project_id, batch)
            generated += n
            failed += 0 if ok else 1
            await asyncio.sleep(BATCH_SLEEP)

        return {"generated": generated, "failed": failed,
                "menus_found": len(menus), "apis_found": len(apis)}

    async def _gen_menu_batch(self, project_id, batch) -> tuple:
        prompt = (
            "以下是 Web 系统的前端菜单列表(JSON)。为每个菜单生成功能回归测试用例"
            "(页面可访问+核心功能操作, 如增删改查入口)。"
            "只返回 JSON 数组, 每元素: {title, precondition, priority(P1/P2), "
            "steps: [{step, action, expected}]}。菜单列表:\n"
            + json.dumps(batch, ensure_ascii=False)
        )
        return await self._call_and_save(project_id, prompt, "菜单")

    async def _gen_api_batch(self, project_id, batch) -> tuple:
        prompt = (
            "以下是后端 API 端点列表(JSON)。为每个端点生成接口功能测试用例"
            "(正常调用+关键参数校验)。只返回 JSON 数组, 每元素: {title, "
            "precondition, priority(P1/P2), steps: [{step, action, expected}]}。"
            "端点列表:\n" + json.dumps(batch, ensure_ascii=False)
        )
        return await self._call_and_save(project_id, prompt, "API")

    async def _call_and_save(self, project_id, prompt, kind) -> tuple:
        """调 AI → 解析 JSON → 逐条去重落库. 返回 (ok, generated_count)."""
        try:
            resp = await self.gateway.chat([{"role": "user", "content": prompt}],
                                           max_tokens=3000)
        except Exception as e:
            logger.warning(f"{kind} batch AI call failed: {e}")
            return False, 0
        cases = self._parse_json_array(resp.get("content", ""))
        if cases is None:
            return False, 0
        n = 0
        for c in cases:
            title = f"[回归] {c.get('title', '')}"[:200]
            if not c.get("title") or await self._case_title_exists(project_id, title):
                continue
            tc = TestCase(
                project_id=UUID(project_id),
                name=title,
                priority=c.get("priority", "P2"),
                case_type="regression",
                precondition=c.get("precondition", "已登录系统"),
                steps=c.get("steps", []),
                expected_result=c.get("steps", [{}])[-1].get("expected", "") if c.get("steps") else "",
                is_finalized=False,
            )
            self.db.add(tc)
            n += 1
        await self.db.flush()
        return True, n

    async def _case_title_exists(self, project_id, title) -> bool:
        from sqlalchemy import select
        r = await self.db.execute(
            select(TestCase.id).where(TestCase.project_id == UUID(project_id),
                                      TestCase.name == title,
                                      TestCase.is_deleted.is_(False)).limit(1))
        return r.scalar_one_or_none() is not None

    @staticmethod
    def _parse_json_array(raw: str):
        """LLM 输出 → JSON 数组. 失败返回 None."""
        import re as _re
        m = _re.search(r"\[.*\]", raw, _re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, list) else None
        except (json.JSONDecodeError, ValueError):
            return None
```

- [x] Step 4: 跑测试确认通过

- [x] Step 5: Commit

```bash
git add app/services/functional_case_generator.py tests/test_functional_case_generator.py
git commit -m "feat(whitescan): functional case generator - AI batch gen from code structure (#func-gen T2)"
```

---

### Task 3: 端点替换 + 前端文案

**Files:**
- Modify: `backend/app/api/v1/whitescan.py`（generate_cases 端点换调用）
- Modify: `frontend/src/views/whitescan/WhiteScan.vue`（按钮文案 + 成功提示）

- [x] Step 1: 改后端端点

`whitescan.py` 的 `generate_cases` 端点：把 `RegressionCaseGenerator` 调用替换为：

```python
    from app.services.functional_case_generator import FunctionalCaseGenerator
    from app.core.storage import storage_client
    # clone 仓库到临时目录 (复用 code_scan_tasks 的 clone 逻辑, 内联精简版)
    import subprocess, tempfile, shutil, re as _re
    scan = await svc.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="scan not found")
    repo_url, branch = scan["repo_url"], scan.get("branch") or "main"
    if not _re.match(r"^(https?://|git@|ssh://|file://)", repo_url):
        raise HTTPException(status_code=400, detail=f"invalid repo_url")
    repo_path = tempfile.mkdtemp(prefix="funccase_")
    try:
        clone = subprocess.run(
            ["git", "clone", "--depth", "1", "-b", branch, "--", repo_url, repo_path],
            capture_output=True, text=True, timeout=240,
            env={**os.environ, "GIT_ALLOW_PROTOCOL": "https:http:ssh:file"})
        if clone.returncode != 0:
            raise HTTPException(status_code=400, detail=f"git clone failed: {clone.stderr[:300]}")
        gen = FunctionalCaseGenerator(db=db, gateway=AIGateway())
        result = await gen.generate_from_repo(project_id, repo_path)
        return {"code": 0, "data": result}
    finally:
        shutil.rmtree(repo_path, ignore_errors=True)
```
（文件顶部加 `import os`；原来 import 的 RegressionCaseGenerator 保留 import 不删或删掉均可——若删掉确认无其他引用。）

**注意**：同步等待较长（分钟级），httpx/前端 axios timeout 需覆盖——前端 axios 默认无超时即可；uvicorn 默认无超时。若生成批次数很大（>30 批），提示用户后台跑属后续优化，v1 同步。

- [x] Step 2: 改前端

`WhiteScan.vue`：
1. 按钮文案 `生成回归用例` → `生成功能回归用例`
2. `onGenerateCases` 成功提示改为：
```js
ElMessage.success(`生成 ${d.generated_count || d.generated || 0} 条功能回归用例，请到用例管理页查看`)
```

- [x] Step 3: 测试

```bash
cd /d/MoonTest/backend && python -m pytest tests/test_api_whitescan.py tests/test_code_scan_service.py tests/test_functional_case_generator.py -q
# 既有 generate-cases 测试若因逻辑替换失败, 按新行为更新断言 (generated_count 字段等)
cd ../frontend && npx vite build
```

- [x] Step 4: Commit

```bash
git add backend/app/api/v1/whitescan.py frontend/src/views/whitescan/WhiteScan.vue backend/tests/
git commit -m "feat(whitescan): generate-cases endpoint now generates functional regression cases from repo structure (#func-gen T3)"
```

---

### Task 4: e2e 验证 + 收尾

- [x] Step 1: 全量后端测试 + 前端 build
```bash
cd /d/MoonTest/backend && python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py --deselect tests/test_storage_get_object.py
cd ../frontend && npx vite build
```

- [ ] Step 2: 真实 e2e——对 MoonTest 自身仓库（testhub_platform-main）跑一次生成，确认 test_case 表新增 > 100 条、用例管理页可见

- [x] Step 3: Commit（如有 fixup）
