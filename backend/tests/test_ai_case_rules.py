"""W6 AI case rules + SSE stage convergence tests."""
import inspect
import pytest
from pydantic import ValidationError

from app.schemas.generation import GenerationRules
from app.services import test_case_generator, test_point_generator


# ---------------------------------------------------------------------------
# GenerationRules (4 switches, automation_thinking forced on)
# ---------------------------------------------------------------------------

def test_rules_automation_thinking_forced_true():
    r = GenerationRules(automation_thinking=False, boundary_value=True,
                        scenario_analysis=True, equivalence_partition=True)
    assert r.automation_thinking is True  # forced


def test_rules_defaults():
    r = GenerationRules()
    assert r.automation_thinking is True
    assert r.boundary_value is True
    assert r.scenario_analysis is True
    assert r.equivalence_partition is True


def test_rules_can_disable_optional_switches():
    r = GenerationRules(boundary_value=False, scenario_analysis=False,
                        equivalence_partition=False)
    assert r.boundary_value is False
    assert r.scenario_analysis is False
    assert r.equivalence_partition is False
    # automation_thinking still forced on
    assert r.automation_thinking is True


# ---------------------------------------------------------------------------
# Generator prompt alignment (forbidden words + action candidates)
# ---------------------------------------------------------------------------

def test_case_generator_prompt_no_verify_action_and_has_forbidden_words():
    src = inspect.getsource(test_case_generator)
    # verify must NOT be an allowed action candidate
    assert '"action": "verify"' not in src
    # forbidden words injected into the prompt
    assert "观察" in src
    assert "验证" in src


def test_point_generator_type_label_5_enums():
    src = inspect.getsource(test_point_generator)
    assert "正常流程" in src
    assert "异常流程" in src
    assert "边界值" in src
    assert "等价类" in src
    assert "场景法" in src


def test_point_generator_default_type_label_is_normal_flow():
    # the fallback when AI omits type_label should be 正常流程, not 功能
    src = inspect.getsource(test_point_generator)
    assert '"功能"' not in src
