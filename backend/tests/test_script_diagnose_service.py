# backend/tests/test_script_diagnose_service.py
"""Diagnose service 4-category attribution tests."""
import asyncio
from app.services.script_diagnose_service import (
    classify_failure, ScriptDiagnoseService, DATA_ENV_KEYWORDS,
)


class TestClassifyFailure:
    def test_locate_failed_is_script_problem(self):
        card = classify_failure(error_type="locate_failed", error_msg="Element not found", failed_step=2)
        assert card["category"] == "script_problem"
        assert card["can_fix"] is True

    def test_assertion_failed_is_page_bug(self):
        card = classify_failure(error_type="assertion_failed", error_msg="expected X got Y", failed_step=1)
        assert card["category"] == "page_bug"
        assert card["can_fix"] is False

    def test_data_env_keyword_overrides(self):
        card = classify_failure(error_type="script_error", error_msg="数据重复", failed_step=1)
        assert card["category"] == "data_env"
        assert card["can_fix"] is False

    def test_missing_type_is_ambiguous(self):
        card = classify_failure(error_type=None, error_msg="something", failed_step=None)
        assert card["category"] == "ambiguous"


class TestDiagnoseService:
    def test_cannot_fix_returns_card_only(self):
        svc = ScriptDiagnoseService(gateway=None)
        card = asyncio.run(svc.diagnose(
            error_type="assertion_failed", error_msg="x", script_fragment="y",
            failed_step=1))
        assert card["can_fix"] is False
        assert card["revised_step"] is None
