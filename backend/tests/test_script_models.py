"""ScriptAsset + ConvertSession model tests."""
from app.models.test_case import ScriptAsset
from app.models.script import ConvertSession


class TestScriptAssetColumns:
    def test_has_name_and_project_id(self):
        cols = {c.name for c in ScriptAsset.__table__.c}
        assert "name" in cols
        assert "project_id" in cols
        assert "description" in cols
        assert "step_mapping" in cols
        assert "locator_source" in cols
        assert "ai_diagnosis" in cols

    def test_has_unique_project_name(self):
        from sqlalchemy import UniqueConstraint
        uqs = [c for c in ScriptAsset.__table__.constraints if isinstance(c, UniqueConstraint)]
        assert any(c.name == "uq_script_asset_project_name" for c in uqs)


class TestConvertSessionColumns:
    def test_required_columns(self):
        cols = {c.name for c in ConvertSession.__table__.c}
        for expected in ("id", "project_id", "case_ids", "ai_optimize",
                         "status", "progress", "tokens_used", "created_at"):
            assert expected in cols
