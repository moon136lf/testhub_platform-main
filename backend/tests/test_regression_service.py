"""Regression (#8) tests (mock db / pure-function rule engine)."""
import asyncio
from datetime import datetime, timedelta, timezone
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
        from app.models.regression import RegressionSet
        existing = RegressionSet(project_id=uuid4(), script_id=uuid4(),
                                 ai_suggested=False, actual_included=False,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=existing)])
        svc = RegressionService(db)
        asyncio_run(svc.set_member("p1", existing.script_id, action="add"))
        assert existing.actual_included is True
        assert existing.include_source == "manual"

    def test_remove_sets_manual(self):
        from app.models.regression import RegressionSet
        existing = RegressionSet(project_id=uuid4(), script_id=uuid4(),
                                 ai_suggested=True, actual_included=True,
                                 include_source="ai")
        db = FakeRegressionDB([FakeResult(scalar=existing)])
        svc = RegressionService(db)
        asyncio_run(svc.set_member("p1", existing.script_id, action="remove"))
        assert existing.actual_included is False
        assert existing.include_source == "manual"
