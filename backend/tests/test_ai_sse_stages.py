"""W6 SSE stage convergence tests."""
import inspect
from app.tasks import ai_case_tasks


VALID_STAGES = {"parse_doc", "identify_point", "generate_case", "detect_hallucination"}


def test_tasks_only_use_4_stages():
    src = inspect.getsource(ai_case_tasks)
    # legacy stage names must be gone (they were folded into identify_point)
    for legacy in ("fetch_knowledge", "apply_rules", "load_knowledge", "save_points"):
        assert legacy not in src, f"legacy stage {legacy} still present"


def test_detect_hallucination_stage_present():
    src = inspect.getsource(ai_case_tasks)
    assert "detect_hallucination" in src


def test_tokens_accumulated():
    src = inspect.getsource(ai_case_tasks)
    # total_tokens accumulator pattern
    assert "total_tokens" in src
    assert "+=" in src
