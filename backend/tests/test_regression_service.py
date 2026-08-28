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
