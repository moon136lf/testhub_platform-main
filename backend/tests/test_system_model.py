"""System settings model tests."""
from app.models.system import SystemSetting, TestEnv, TokenQuota, OperationLog


def test_system_setting_fields():
    cols = {c.name for c in SystemSetting.__table__.columns}
    assert {"id", "category", "key", "value", "value_encrypted",
            "value_type", "is_secret", "description", "updated_by", "updated_at"} <= cols
    # category is an enum-like carrying the "ai" value (SQLAlchemy 2.0: str(type)
    # renders VARCHAR(N); the enum literals live on `.enums`)
    assert "ai" in SystemSetting.__table__.c.category.type.enums
    # unique constraint on (category, key)
    uqs = [str(c) for c in SystemSetting.__table__.constraints
           if c.__class__.__name__ == "UniqueConstraint"]
    assert any("category" in u and "key" in u for u in uqs)


def test_test_env_fields():
    cols = {c.name for c in TestEnv.__table__.columns}
    assert {"id", "name", "url", "env_type", "status", "credentials",
            "created_by", "created_at", "updated_at"} <= cols
    # credentials is JSONB
    assert TestEnv.__table__.c.credentials.type.__class__.__name__ == "JSONB"


def test_token_quota_fields():
    cols = {c.name for c in TokenQuota.__table__.columns}
    assert {"id", "project_id", "total_quota", "alert_threshold", "updated_at"} <= cols
    assert TokenQuota.__table__.c.total_quota.default.arg == 100000
    assert TokenQuota.__table__.c.alert_threshold.default.arg == 10


def test_operation_log_fields():
    cols = {c.name for c in OperationLog.__table__.columns}
    assert {"id", "module", "action", "target_type", "target_id",
            "detail", "operator", "ip", "created_at"} <= cols
    assert OperationLog.__table__.c.detail.type.__class__.__name__ == "JSONB"


def test_models_registered_in_init():
    import app.models as m
    assert hasattr(m, "SystemSetting")
    assert hasattr(m, "TestEnv")
    assert hasattr(m, "TokenQuota")
    assert hasattr(m, "OperationLog")
