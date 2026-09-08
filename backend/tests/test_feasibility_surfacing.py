"""可自动化评级透出锁定：feasibility_level 在列表/详情响应中可用（阶段2 T5）

注：响应模型的 feasibility_level 无 pattern 约束（pattern 在更新 schema
CaseUpdateRequest 上），因此锁定点为字段透出存在性 + service 层传值。
"""

import pytest

from app.schemas.test_case import CaseResponse, CaseDetailResponse


def test_list_response_schema_has_feasibility():
    """响应模型字段存在 = FastAPI 会透出到列表/详情接口"""
    assert "feasibility_level" in CaseResponse.model_fields
    assert "feasibility_level" in CaseDetailResponse.model_fields
    assert "cannot_automate_reason" in CaseDetailResponse.model_fields


def _base_kwargs():
    return dict(
        id="x",
        project_id="p",
        name="n",
        priority="P1",
        case_type="functional",
        automation_status="manual",
        expected_result="ok",
        is_finalized=False,
        version=1,
        hallucination_status="normal",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def test_response_models_accept_feasibility():
    """构造时 feasibility_level 可设值/缺省为 None（透出行为正常）"""
    kwargs = _base_kwargs()
    assert CaseResponse(feasibility_level="full", **kwargs).feasibility_level == "full"
    assert CaseResponse(**kwargs).feasibility_level is None

    detail_kwargs = dict(kwargs, steps=[], is_deleted=False)
    assert CaseDetailResponse(feasibility_level="none", **detail_kwargs).feasibility_level == "none"


def test_update_schema_rejects_invalid_feasibility():
    """更新入口（带 pattern）挡住非法值，保证库中只有合法评级"""
    from pydantic import ValidationError

    from app.schemas.test_case import CaseUpdateRequest

    with pytest.raises(ValidationError):
        CaseUpdateRequest(feasibility_level="bogus")
