"""W5 review/refinement tests."""
from uuid import uuid4
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.test_case import TestCase
from app.services.case_refiner import (
    CaseRefiner,
    FORBIDDEN_TAUTOLOGICAL_ASSERTIONS,
    AMBIGUOUS_EXPECTED,
)


# ---------------------------------------------------------------------------
# Model fields
# ---------------------------------------------------------------------------

def test_testcase_has_review_fields():
    cols = {c.name for c in TestCase.__table__.columns}
    assert {"review_status", "review_comment", "feasibility_level",
            "cannot_automate_reason", "refinement_report", "refined_at"} <= cols


def test_review_status_default_pending():
    col = TestCase.__table__.c.review_status
    assert col.default.arg == "pending"


# ---------------------------------------------------------------------------
# Rule layer
# ---------------------------------------------------------------------------

def _case(steps, expected="正常", precondition=""):
    return {
        "name": "c", "priority": "P1", "case_type": "functional",
        "precondition": precondition, "steps": steps, "expected_result": expected,
    }


class TestRuleLayer:
    def test_soft_assertion_detected(self):
        case = _case([{"step": 1, "action": "观察页面跳转", "expected": "页面变化"}])
        r = CaseRefiner()._check_assertions(case)
        assert any(s["dimension"] == "断言增强" for s in r)

    def test_missing_precondition_flagged(self):
        case = _case([{"step": 1, "action": "点击提交", "expected": "成功"}], precondition="")
        r = CaseRefiner()._check_data_setup(case)
        assert r  # non-empty -> flagged

    def test_visual_action_marked_manual(self):
        case = _case([{"step": 1, "action": "验证布局美观", "expected": "布局好看"}])
        feas = CaseRefiner()._assess_feasibility(case, page_elements=None)
        assert feas["feasibility_level"] == "manual"
        assert feas["cannot_automate_reason"]

    def test_no_elements_skipped_but_report_complete(self):
        case = _case([{"step": 1, "action": "观察结果", "expected": "正常"}])
        report = CaseRefiner().refine_sync(case, page_elements=None)
        assert "score" in report
        assert "suggestions" in report
        assert 0 <= report["score"] <= 100

    def test_forbidden_keywords_include_basics(self):
        assert "观察" in FORBIDDEN_TAUTOLOGICAL_ASSERTIONS
        assert "验证" in FORBIDDEN_TAUTOLOGICAL_ASSERTIONS

    def test_ambiguous_expected_flagged(self):
        case = _case([{"step": 1, "action": "点击登录", "expected": "成功"}],
                     expected="系统正常处理")
        r = CaseRefiner()._check_assertions(case)
        assert any(s["issue"].startswith("预期结果模糊") for s in r)


# ---------------------------------------------------------------------------
# Service refine_case + apply_suggestions
# ---------------------------------------------------------------------------

@pytest.fixture
def svc_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    db.add = Mock()
    return db


def _refine_case_mock():
    case = Mock()
    case.id = uuid4()
    case.project_id = uuid4()
    case.point_id = None
    case.steps = [{"step": 1, "action": "观察跳转", "expected": "正常"}]
    case.expected_result = "正常"
    case.precondition = ""
    case.case_type = "functional"
    case.priority = "P1"
    case.automation_status = "pending"
    case.name = "c"
    case.version = 1
    case.hallucination_status = "normal"
    case.is_finalized = False
    case.is_deleted = False
    case.created_by = "u"
    case.created_at = case.updated_at = None
    case.review_status = "pending"
    case.review_comment = None
    case.feasibility_level = None
    case.cannot_automate_reason = None
    case.refinement_report = None
    case.refined_at = None
    return case


class TestRefineService:
    @pytest.mark.asyncio
    async def test_refine_case_writes_report_and_fields(self, svc_db):
        from app.services.test_case_service import TestCaseService

        case = _refine_case_mock()
        svc_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=case))

        svc = TestCaseService(svc_db)
        report = await svc.refine_case(str(case.id))
        assert case.refinement_report is not None
        assert case.feasibility_level in ("manual", "partial", "full")
        assert case.refined_at is not None
        assert "score" in report

    @pytest.mark.asyncio
    async def test_refine_case_returns_none_when_missing(self, svc_db):
        from app.services.test_case_service import TestCaseService

        svc_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        svc = TestCaseService(svc_db)
        assert await svc.refine_case(str(uuid4())) is None

    @pytest.mark.asyncio
    async def test_apply_suggestions_applies_steps_and_marks(self, svc_db):
        from app.services.test_case_service import TestCaseService

        case = _refine_case_mock()
        # pre-existing report with a refined steps block + one suggestion
        case.refinement_report = {
            "score": 70,
            "refined_case": {
                "name": "c", "priority": "P1", "case_type": "functional",
                "precondition": "已登录", "steps": [{"step": 1, "action": "断言URL为首页", "expected": "url matches"}],
                "expected_result": "进入首页",
            },
            "suggestions": [
                {"id": "S1", "dimension": "断言增强", "severity": "high",
                 "target_step": 1, "issue": "软断言", "suggestion": "转硬断言", "status": "pending"},
            ],
            "normativity": {"steps_complete": True, "assertion_executable": True, "precondition_complete": True},
            "reuse_level": "new",
            "feasibility_level": "full",
            "cannot_automate_reason": "",
        }
        svc_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=case))

        svc = TestCaseService(svc_db)
        result = await svc.apply_suggestions(str(case.id), None)
        assert case.steps == case.refinement_report["refined_case"]["steps"]
        assert case.version == 2  # incremented
        assert case.refinement_report["suggestions"][0]["status"] == "applied"
        assert result is not None

    @pytest.mark.asyncio
    async def test_apply_suggestions_specific_ids(self, svc_db):
        from app.services.test_case_service import TestCaseService

        case = _refine_case_mock()
        case.refinement_report = {
            "refined_case": {"steps": [{"step": 1, "action": "断言", "expected": "x"}]},
            "suggestions": [
                {"id": "S1", "dimension": "断言增强", "status": "pending"},
                {"id": "S2", "dimension": "异常路径补充", "status": "pending"},
            ],
        }
        svc_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=case))
        svc = TestCaseService(svc_db)
        await svc.apply_suggestions(str(case.id), ["S2"])
        statuses = {s["id"]: s["status"] for s in case.refinement_report["suggestions"]}
        assert statuses["S2"] == "applied"
        assert statuses["S1"] == "pending"

    @pytest.mark.asyncio
    async def test_apply_suggestions_missing_report_returns_none(self, svc_db):
        from app.services.test_case_service import TestCaseService

        case = _refine_case_mock()
        case.refinement_report = None
        svc_db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=case))
        svc = TestCaseService(svc_db)
        assert await svc.apply_suggestions(str(case.id), None) is None


# ---------------------------------------------------------------------------
# LLM rewrite on apply (阶段3 T6)
# ---------------------------------------------------------------------------

class TestLLMRewriteOnApply:
    @pytest.mark.asyncio
    async def test_rewrite_soft_assert_steps(self):
        """应用「断言增强」建议 → LLM 改写软断言步骤 → case.steps 实际更新"""
        from app.services.case_refiner import llm_rewrite_steps

        steps = [
            {"step": 1, "action": "打开页面", "target": "", "data": "", "expected": "页面展示"},
            {"step": 2, "action": "查看列表", "target": ".list", "data": "", "expected": "看到数据"},
        ]
        suggestions = [
            {"id": "S1", "dimension": "断言增强", "target_step": 2,
             "issue": "步骤2含软断言词「查看」", "suggestion": "转为硬断言，验证操作导致的业务结果"},
        ]

        async def fake_chat(messages, **kw):
            return {"content": '[{"step": 2, "action": "断言列表加载", "target": ".list", "data": "", "expected": "列表显示3条数据"}]', "tokens": 100}

        rewritten = await llm_rewrite_steps(steps, suggestions, chat_fn=fake_chat)
        # 步骤1 不变；步骤2 被改写
        assert rewritten[0]["action"] == "打开页面"
        assert rewritten[1]["action"] == "断言列表加载"
        assert rewritten[1]["expected"] == "列表显示3条数据"

    @pytest.mark.asyncio
    async def test_rewrite_llm_failure_returns_original(self):
        """LLM 失败 → 返回原步骤（不阻塞应用流程）"""
        from app.services.case_refiner import llm_rewrite_steps

        async def fake_chat(messages, **kw):
            raise Exception("LLM down")

        steps = [{"step": 1, "action": "查看列表", "target": ".l", "data": "", "expected": "看到"}]
        rewritten = await llm_rewrite_steps(steps, [{"id": "S1", "dimension": "断言增强", "target_step": 1}], chat_fn=fake_chat)
        assert rewritten == steps

    @pytest.mark.asyncio
    async def test_rewrite_invalid_llm_output_keeps_step(self):
        """LLM 返回非法结构（缺 step/action）→ 该步保持原样"""
        from app.services.case_refiner import llm_rewrite_steps

        async def fake_chat(messages, **kw):
            return {"content": '[{"foo": "bar"}]', "tokens": 10}

        steps = [{"step": 1, "action": "查看", "target": ".l", "data": "", "expected": "x"}]
        rewritten = await llm_rewrite_steps(steps, [{"id": "S1", "dimension": "断言增强", "target_step": 1}], chat_fn=fake_chat)
        assert rewritten[0]["action"] == "查看"
