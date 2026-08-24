"""Script schema validation tests."""
import pytest
from pydantic import ValidationError
from app.schemas.script import (
    ConvertRequest, ConfirmResponse, DiagnoseRequest,
    DiagnosisCard, LOCATOR_SOURCES, SCRIPT_STATUSES, ERROR_TYPES,
)


class TestEnums:
    def test_locator_sources(self):
        assert LOCATOR_SOURCES == ("element_library", "ai_generated", "mixed", "none_draft")

    def test_script_statuses(self):
        assert SCRIPT_STATUSES == ("draft", "generated", "confirmed")

    def test_error_types(self):
        assert ERROR_TYPES == ("locate_failed", "timeout", "assertion_failed", "script_error")


class TestConvertRequest:
    def _base(self):
        return dict(project_id="0"*8 + "-" + "0"*4 + "-" + "0"*4 + "-" + "0"*4 + "-" + "0"*12,
                    case_ids=["a"*8 + "-0000-0000-0000-" + "a"*12])

    def test_minimal(self):
        r = ConvertRequest(**self._base())
        assert r.ai_optimize is False

    def test_empty_case_ids_rejected(self):
        with pytest.raises(ValidationError):
            ConvertRequest(**{**self._base(), "case_ids": []})


class TestDiagnoseRequest:
    def test_requires_error_type(self):
        with pytest.raises(ValidationError):
            DiagnoseRequest(error_type=None, error_msg="x", script_fragment="y")

    def test_invalid_error_type(self):
        with pytest.raises(ValidationError):
            DiagnoseRequest(error_type="bogus", error_msg="x", script_fragment="y")
