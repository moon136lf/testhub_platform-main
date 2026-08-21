"""W1 bugfix tests."""
import inspect
from app.api.v1 import ai_case_generation


def test_get_test_points_does_not_reference_is_deleted():
    """TestPoint has no is_deleted column; the query must not filter on it."""
    src = inspect.getsource(ai_case_generation)
    assert "TestPoint.is_deleted" not in src


def test_testpoint_model_has_no_is_deleted():
    from app.models.test_case import TestPoint
    assert not hasattr(TestPoint, "is_deleted")
