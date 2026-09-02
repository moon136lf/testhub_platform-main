"""FunctionalCaseGenerator tests (mock gateway/db, real batching logic)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock


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

        # 静态解析用真实文件
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text("{ path: '/dashboard', name: 'D', meta: { title: '仪表盘' } }", encoding="utf-8")
        apidir = tmp_path / "api" / "v1"; apidir.mkdir(parents=True)
        (apidir / "projects.py").write_text(
            '@router.get("/projects")\nasync def list_projects():\n    """获取项目列表"""\n', encoding="utf-8")

        db = _make_db()
        gw = _gw_ok([MENU_JSON, API_JSON])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
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
        db = MagicMock()
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
