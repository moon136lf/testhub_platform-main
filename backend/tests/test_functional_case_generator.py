"""FunctionalCaseGenerator tests (mock gateway/db, real batching logic)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock


def asyncio_run(coro): return asyncio.run(coro)


def _make_db(existing_titles=()):
    from app.models.case_batch import CaseBatch
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
        # CaseBatch 查重 → 不存在; 其余按队列 (title 查重)
        if "case_batch" in str(q):
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r
        if db._results:
            return db._results.pop(0)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    db.execute = execute
    db.add = lambda o: db.added.append(o)
    async def _flush(): pass
    db.flush = _flush
    async def _get(cls, bid):
        return None
    db.get = _get
    return db


def _added_cases(db):
    """db.added 中的 TestCase（前两项是 CaseBatch）。"""
    from app.models.test_case import TestCase
    return [o for o in db.added if isinstance(o, TestCase)]


def _added_batches(db):
    from app.models.case_batch import CaseBatch
    return [o for o in db.added if isinstance(o, CaseBatch)]


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
        assert len(_added_cases(db)) >= 2
        tc = _added_cases(db)[0]
        assert tc.project_id == "p1"
        assert "回归" in tc.name
        assert tc.case_type == "functional"
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
        async def _execute(q):
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r
        db.execute = _execute
        async def _get(cls, bid):
            return None
        db.get = _get
        gw = _gw_ok([MENU_JSON])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        # 查重按生成的 title: monkeypatch _case_title_exists 返回 True
        gen._case_title_exists = AsyncMock(return_value=True)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        assert result["generated"] == 0
        assert len(_added_cases(db)) == 0

    def test_non_dict_elements_skipped(self, tmp_path):
        """JSON 数组混入非 dict 元素 → 跳过不崩溃."""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text("{ path: '/x', meta: { title: 'X' } }", encoding="utf-8")
        mixed = '''[42, "oops", null,
  {"title": "混合-页面访问", "priority": "P1",
   "steps": [{"step": 1, "action": "a", "expected": "e"}]}
]'''
        db = _make_db()
        gw = _gw_ok([mixed])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        assert result["generated"] == 1
        assert len(_added_cases(db)) == 1
        assert _added_cases(db)[0].name.startswith("[回归]")

    def test_same_batch_duplicate_titles(self, tmp_path):
        """同批两个相同 title → 只落库一条."""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text("{ path: '/y', meta: { title: 'Y' } }", encoding="utf-8")
        dup = '''[
  {"title": "重复-页面", "priority": "P1", "steps": [{"step": 1, "action": "a", "expected": "e"}]},
  {"title": "重复-页面", "priority": "P2", "steps": [{"step": 1, "action": "a", "expected": "e"}]}
]'''
        db = _make_db()
        gw = _gw_ok([dup])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        assert result["generated"] == 1
        assert len(_added_cases(db)) == 1

    def test_invalid_priority_defaults_p2(self, tmp_path):
        """priority 为非法值 → 默认 P2."""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text("{ path: '/z', meta: { title: 'Z' } }", encoding="utf-8")
        bad = '''[
  {"title": "优先级异常-页面", "priority": "P9", "steps": [{"step": 1, "action": "a", "expected": "e"}]}
]'''
        db = _make_db()
        gw = _gw_ok([bad])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        assert result["generated"] == 1
        assert _added_cases(db)[0].priority == "P2"

    def test_garbage_steps_normalized(self, tmp_path):
        """LLM steps 含垃圾项 → 过滤+重编号; 全非法 → []."""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text("{ path: '/g', meta: { title: 'G' } }", encoding="utf-8")
        messy = '''[
  {"title": "脏步骤-页面", "priority": "P1", "steps": [
    {"step": "1.", "action": "合法动作", "expected": "合法预期"},
    "not-a-dict",
    {"step": 2, "action": "", "expected": "空动作应被过滤"},
    {"step": 3, "action": "合法动作2", "expected": "合法预期2"}
  ]},
  {"title": "全空步骤-页面", "priority": "P2", "steps": [
    {"step": 1, "action": "", "expected": ""}
  ]}
]'''
        db = _make_db()
        gw = _gw_ok([messy])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        assert result["generated"] == 2
        s1 = _added_cases(db)[0].steps
        assert [s["step"] for s in s1] == [1, 2]  # 过滤+重编号
        assert s1[0]["action"] == "合法动作"
        assert _added_cases(db)[1].steps == []  # 全非法 → 空
        assert _added_cases(db)[1].expected_result == ""

    def test_integrity_error_does_not_kill_subsequent_batches(self, tmp_path):
        """批 flush IntegrityError 后, 后续批仍能正常落库（savepoint 隔离）. #T2 review Critical1"""
        from contextlib import asynccontextmanager
        from app.services.functional_case_generator import FunctionalCaseGenerator
        from sqlalchemy.exc import IntegrityError
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text(
            "{ path: '/a', meta: { title: 'A' } },\n{ path: '/b', meta: { title: 'B' } },\n"
            "{ path: '/c', meta: { title: 'C' } },\n{ path: '/d', meta: { title: 'D' } },\n"
            "{ path: '/e', meta: { title: 'E' } },\n{ path: '/f', meta: { title: 'F' } },",
            encoding="utf-8")  # 6 菜单 → 2 批
        db = _make_db()
        rolled_back = []
        call_count = [0]
        async def _flush():
            call_count[0] += 1
            # 批次建行 flush(2次) 放行; 第一批用例 flush 抛 IntegrityError, 之后成功
            if len(db.added) > 2 and call_count[0] == 3:
                raise IntegrityError("dup", None, Exception())
        db.flush = _flush
        db.rollback = lambda: rolled_back.append(True)
        @asynccontextmanager
        async def _nested():
            yield
        db.begin_nested = _nested
        gw = _gw_ok([MENU_JSON, MENU_JSON.replace("仪表盘", "页面")])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        # 第一批失败计 failed, 第二批仍成功落库; 不应调用全局 rollback
        assert result["generated"] >= 1
        assert result["failed"] == 1
        assert rolled_back == []
        assert len(_added_cases(db)) >= 2  # 第二批用例仍被 add

    def test_flush_integrity_error_rolls_back(self, tmp_path):
        """flush 抛 IntegrityError → savepoint 隔离, 批计 failed, 不调全局 rollback. #T2 review"""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        from sqlalchemy.exc import IntegrityError
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text("{ path: '/r', meta: { title: 'R' } }", encoding="utf-8")
        db = _make_db()
        rolled_back = []
        call_count = [0]
        async def _flush():
            # 批次建行 flush(2次) 放行, 用例落库 flush 抛错
            call_count[0] += 1
            if len(db.added) > 2:
                raise IntegrityError("dup", None, Exception())
        async def _rollback():
            rolled_back.append(True)
        db.flush = _flush
        db.rollback = _rollback
        gw = _gw_ok([MENU_JSON])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        # flush 失败 → 该批计 failed; savepoint 隔离, 不应回滚外层事务
        assert result["generated"] == 0
        assert result["failed"] >= 1
        assert rolled_back == []


class TestPromptEnhancement:
    """V1.1 增强: 菜单批 prompt 要求增删改查+流程用例; API 批过滤非业务端点并加前缀."""

    def test_menu_prompt_requires_crud_and_flow(self, tmp_path):
        from app.services.functional_case_generator import FunctionalCaseGenerator
        rdir = tmp_path / "src" / "router"; rdir.mkdir(parents=True)
        (rdir / "index.js").write_text("{ path: '/d', meta: { title: '仪表盘' } }", encoding="utf-8")
        db = _make_db()
        gw = _gw_ok([MENU_JSON])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        prompt = gw.chat.call_args[0][0][0]["content"]
        assert "增删改查" in prompt
        assert "流程" in prompt
        assert "2-5" in prompt  # 每菜单用例数指引

    def test_api_noise_endpoints_filtered(self, tmp_path):
        """health/ping/sse/docs 等非业务端点不生成用例."""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        apidir = tmp_path / "api" / "v1"; apidir.mkdir(parents=True)
        (apidir / "health.py").write_text(
            '@router.get("/")\nasync def health():\n    """健康检查"""\n'
            '@router.get("/ping")\nasync def ping():\n    """存活探活"""\n', encoding="utf-8")
        (apidir / "projects.py").write_text(
            '@router.get("/projects")\nasync def list_projects():\n    """获取项目列表"""\n', encoding="utf-8")
        db = _make_db()
        gw = _gw_ok([API_JSON])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        result = asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        prompt = gw.chat.call_args[0][0][0]["content"]
        assert "/projects" in prompt
        assert "/ping" not in prompt
        assert "健康检查" not in prompt
        assert result["generated"] >= 1

    def test_api_cases_prefixed(self, tmp_path):
        """API 用例名称加 [回归-接口] 前缀, 与页面用例区分."""
        from app.services.functional_case_generator import FunctionalCaseGenerator
        apidir = tmp_path / "api" / "v1"; apidir.mkdir(parents=True)
        (apidir / "projects.py").write_text(
            '@router.get("/projects")\nasync def list_projects():\n    """获取项目列表"""\n', encoding="utf-8")
        db = _make_db()
        gw = _gw_ok([API_JSON])
        gen = FunctionalCaseGenerator(db=db, gateway=gw)
        asyncio_run(gen.generate_from_repo(project_id="p1", repo_path=str(tmp_path)))
        assert _added_cases(db)[0].name.startswith("[回归-接口]")
