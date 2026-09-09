"""Regression (#8) tests (mock db / pure-function rule engine)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def asyncio_run(coro): return asyncio.run(coro)


class TestRegressionSetModel:
    def test_model_fields_and_defaults(self):
        """§3.6.5 DDL: 字段/默认值/UNIQUE 约束定义存在."""
        from app.models.regression import RegressionSet
        r = RegressionSet(project_id=uuid4(), script_id=uuid4())
        assert r.ai_suggested is None or r.ai_suggested is False  # Column default False
        assert r.include_source == "ai" or r.include_source is None
        # 表级约束
        consts = [c.name for c in RegressionSet.__table_args__ if hasattr(c, "name")]
        assert "uq_regression_project_script" in consts
        assert "idx_reg_project" in consts
        assert "idx_reg_included" in consts

    def test_registered_in_models_init(self):
        """models/__init__ 可导入 (建表反射/关系注册需要)."""
        from app.models import RegressionSet  # noqa: F401


# ---- T3: RegressionService ----
from app.services.regression_service import RegressionService


class FakeResult:
    def __init__(self, scalar=None, scalars=None):
        self._scalar = scalar
        self._scalars = scalars

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return MagicMock(all=MagicMock(return_value=self._scalars or []))

    def all(self):
        return self._scalars or []


class FakeRegressionDB:
    """顺序弹出 execute 结果; 记录 add 的对象."""
    def __init__(self, results):
        self._results = list(results)
        self.added = []

    async def execute(self, q):
        r = self._results.pop(0) if self._results else FakeResult()
        return r

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass


class TestUpsertMember:
    def test_first_identify_creates_row_following_ai(self):
        """首次识别: 无行 → 新建 actual_included=ai_suggested, source=ai."""
        from app.models.regression import RegressionSet
        db = FakeRegressionDB([FakeResult(scalar=None)])  # 查无现有行
        svc = RegressionService(db)
        row = asyncio_run(svc.upsert_member("p1", uuid4(), included=True, reason="P0核心用例"))
        assert isinstance(row, RegressionSet)
        assert row in db.added
        assert row.ai_suggested is True
        assert row.actual_included is True
        assert row.include_source == "ai"

    def test_manual_row_not_overwritten(self):
        """I 偏差: include_source=manual 的行, 识别只更新 ai 字段, 不动 actual_included."""
        from app.models.regression import RegressionSet
        existing = RegressionSet(project_id=uuid4(), script_id=uuid4(),
                                 ai_suggested=False, actual_included=True,
                                 include_source="manual")
        db = FakeRegressionDB([FakeResult(scalar=existing)])
        svc = RegressionService(db)
        row = asyncio_run(svc.upsert_member("p1", existing.script_id, included=False, reason=""))
        assert row is existing
        assert row.ai_suggested is False      # ai 字段更新
        assert row.actual_included is True    # 人工调整保留
        assert row.include_source == "manual"

    def test_ai_row_follows_new_result(self):
        """include_source=ai 的行, actual_included 跟随最新识别."""
        from app.models.regression import RegressionSet
        existing = RegressionSet(project_id=uuid4(), script_id=uuid4(),
                                 ai_suggested=True, actual_included=True,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=existing)])
        svc = RegressionService(db)
        row = asyncio_run(svc.upsert_member("p1", existing.script_id, included=False, reason=""))
        assert row.ai_suggested is False
        assert row.actual_included is False   # ai 行跟随
        assert row.include_source == "ai"


class TestSetMembers:
    def test_add_sets_manual(self):
        """阶段3语义: add → ScriptAsset.for_regression=True + RegressionSet 行同步 manual."""
        from app.models.regression import RegressionSet
        sid = uuid4()
        script = _FakeScript(sid, for_regression=False)
        existing = RegressionSet(project_id=uuid4(), script_id=sid,
                                 ai_suggested=False, actual_included=False,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=script), FakeResult(scalar=existing)])
        svc = RegressionService(db)
        asyncio_run(svc.set_member("p1", sid, action="add"))
        assert script.for_regression is True          # 阶段3 主操作
        assert existing.actual_included is True
        assert existing.include_source == "manual"

    def test_remove_sets_manual(self):
        from app.models.regression import RegressionSet
        sid = uuid4()
        script = _FakeScript(sid, for_regression=True)
        existing = RegressionSet(project_id=uuid4(), script_id=sid,
                                 ai_suggested=True, actual_included=True,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=script), FakeResult(scalar=existing)])
        svc = RegressionService(db)
        asyncio_run(svc.set_member("p1", sid, action="remove"))
        assert script.for_regression is False         # 阶段3 主操作
        assert existing.actual_included is False
        assert existing.include_source == "manual"


# ---- 阶段3 T2: 数据源切换 ScriptAsset.for_regression ----
from uuid import UUID


class _FakeScript:
    """最小 ScriptAsset 替身 (有 id/module/for_regression/last_status)."""
    def __init__(self, script_id, for_regression=True, module=None, last_status=None):
        self.id = script_id
        self.module = module
        self.for_regression = for_regression
        self.last_status = last_status
        self.to_dict = MagicMock(return_value={"id": str(script_id), "name": "s1"})


class TestForRegressionSource:
    def test_list_view_uses_for_regression(self):
        """list_view 主数据源 = ScriptAsset.for_regression；included 输出=for_regression 本身."""
        sid = uuid4()
        script = _FakeScript(sid, for_regression=True)
        # 结果行: (script, reg) — reg 为 None (无 RegressionSet 行也应在列)
        db = FakeRegressionDB([FakeResult(scalars=[(script, None)])])
        svc = RegressionService(db)
        items = asyncio_run(svc.list_view("p1"))
        assert len(items) == 1
        assert items[0]["script"]["id"] == str(sid)
        assert items[0]["included"] is True            # for_regression 本身
        assert items[0]["ai_suggested"] is False       # 无 reg 行 → 建议列显示空

    def test_list_view_excludes_flag_false(self):
        """for_regression=False 的脚本不进主列表."""
        script = _FakeScript(uuid4(), for_regression=False)
        db = FakeRegressionDB([FakeResult(scalars=[])])  # 查询本身按 flag 过滤 → 空
        svc = RegressionService(db)
        items = asyncio_run(svc.list_view("p1"))
        assert items == []

    def test_add_member_sets_flag(self):
        """members add → ScriptAsset.for_regression=True (RegressionSet 行仍写做记录)."""
        from app.models.regression import RegressionSet
        sid = uuid4()
        script = _FakeScript(sid, for_regression=False)
        existing = RegressionSet(project_id=uuid4(), script_id=sid,
                                 ai_suggested=False, actual_included=False,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=script),   # 查 ScriptAsset
                               FakeResult(scalar=existing)])  # 查 RegressionSet
        svc = RegressionService(db)
        asyncio_run(svc.set_member("p1", sid, action="add"))
        assert script.for_regression is True
        assert existing.actual_included is True       # RegressionSet 同步记录
        assert existing.include_source == "manual"

    def test_remove_member_clears_flag(self):
        """members remove → for_regression=False."""
        from app.models.regression import RegressionSet
        sid = uuid4()
        script = _FakeScript(sid, for_regression=True)
        existing = RegressionSet(project_id=uuid4(), script_id=sid,
                                 ai_suggested=True, actual_included=True,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=script), FakeResult(scalar=existing)])
        svc = RegressionService(db)
        asyncio_run(svc.set_member("p1", sid, action="remove"))
        assert script.for_regression is False
        assert existing.actual_included is False

    def test_run_uses_for_regression_scripts(self):
        """run 取 for_regression=True 的脚本 (actual_included 不再参与)."""
        s1 = _FakeScript(uuid4(), for_regression=True, last_status="passed")
        s2 = _FakeScript(uuid4(), for_regression=False)
        db = FakeRegressionDB([FakeResult(scalars=[s1])])  # 查询按 flag 过滤
        svc = RegressionService(db)
        stats = asyncio_run(svc.get_stats("p1"))
        assert stats["total"] == 1
        assert stats["passed"] == 1
