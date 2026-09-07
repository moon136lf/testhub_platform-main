"""W2 schema alignment tests."""
import pytest
from pydantic import ValidationError
from app.schemas.test_case import (
    StepSchema, CaseCreateRequest, CaseFilterParams,
    CASE_TYPES, AUTOMATION_STATUSES, REVIEW_STATUSES, FEASIBILITY_LEVELS,
)


class TestEnumConstants:
    def test_case_types_canonical(self):
        assert CASE_TYPES == ("functional", "interface_case")

    def test_automation_statuses_canonical(self):
        # #4: 'converted' = 已转脚本 (CASE-MGMT-04 流转链: 定稿→已转脚本→已自动化)
        assert AUTOMATION_STATUSES == ("pending", "converted", "automated", "partial_automated")

    def test_review_statuses_canonical(self):
        assert REVIEW_STATUSES == ("pending", "passed", "needs_revision")

    def test_feasibility_levels_canonical(self):
        assert FEASIBILITY_LEVELS == ("full", "partial", "manual")


class TestStepSchema:
    def test_step_field_name_is_step_not_seq(self):
        s = StepSchema(step=1, action="点击登录", expected="跳转首页")
        assert s.step == 1
        with pytest.raises(ValidationError):
            StepSchema(seq=1, action="x", expected="y")  # seq no longer valid

    def test_action_max_length_2000(self):
        with pytest.raises(ValidationError):
            StepSchema(step=1, action="x" * 2001, expected="y")

    def test_expected_max_length_2000(self):
        with pytest.raises(ValidationError):
            StepSchema(step=1, action="x", expected="y" * 2001)


class TestCaseCreateEnumRejection:
    def _base(self):
        return dict(
            project_id="00000000-0000-0000-0000-000000000001",
            name="t", priority="P1", case_type="functional",
            steps=[{"step": 1, "action": "a", "expected": "e"}],
            expected_result="r",
        )

    def test_reject_old_case_type(self):
        with pytest.raises(ValidationError):
            CaseCreateRequest(**{**self._base(), "case_type": "performance"})

    def test_accept_interface_case(self):
        c = CaseCreateRequest(**{**self._base(), "case_type": "interface_case"})
        assert c.case_type == "interface_case"

    def test_reject_cannot_automate(self):
        with pytest.raises(ValidationError):
            CaseCreateRequest(**{**self._base(), "automation_status": "cannot_automate"})

    def test_accept_partial_automated(self):
        c = CaseCreateRequest(**{**self._base(), "automation_status": "partial_automated"})
        assert c.automation_status == "partial_automated"


class TestModelConstraints:
    def test_testcase_has_unique_project_name(self):
        from app.models.test_case import TestCase
        assert any("project_id" in str(c) and "name" in str(c) for c in TestCase.__table__.constraints)

    def test_steps_column_is_jsonb(self):
        from app.models.test_case import TestCase
        col = TestCase.__table__.c.steps
        assert col.type.__class__.__name__ == "JSONB"
