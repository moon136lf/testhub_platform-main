"""step3 接入评分管线 + L3 AI 候选单选测试（方案V1 阶段2/3）。"""
import pytest
from app.services.script_pipeline import step3_match_locators, ActionIntent, ActionWithLocator


class FakeCandidates:
    """find_candidates 协议实现：返回结构化候选。"""
    def __init__(self, by_target):
        self.by_target = by_target

    async def find_candidates(self, project_id, target, intent_action=None, page_id=None):
        return self.by_target.get((target, intent_action), [])


class FakeGateway:
    def __init__(self, pick=0):
        self.pick = pick
        self.calls = []

    async def chat(self, messages):
        self.calls.append(messages)
        return {"content": f'{{"pick": {self.pick}}}'}


def _act(step, action, target, value=None):
    return ActionIntent(step=step, action=action, target=target, value=value)


@pytest.mark.asyncio
async def test_step3_l2_hit_binds_element():
    cands = {("账号输入框", "input"): [
        {"element_id": "el-1", "element_name": "请输入账号", "locator": "#zh",
         "confidence": 5, "score": 0.82, "match_level": "L2"}]}
    results = await step3_match_locators(
        [_act(1, "fill", "账号输入框", "test02")], "p1",
        lookup=FakeCandidates(cands), ai_optimize=False, gateway=None)
    r = results[0]
    assert r.locator == "#zh"
    assert r.locator_status == "matched"
    assert r.element_id == "el-1"
    assert r.element_name == "请输入账号"
    assert r.match_score == 0.82


def _make_action(**kw):
    base = dict(step=1, action="fill", target="账号输入框", value="x",
                locator="#zh", locator_status="matched", locator_source="element_library",
                element_id="el-1", element_name="请输入账号", match_score=0.82, match_level="L2")
    base.update(kw)
    return ActionWithLocator(**base)


def test_step_mapping_carries_binding_fields():
    """step_mapping 落库须透传 element_id/match_level/match_score（前端绑定态数据源）。"""
    from app.services.script_pipeline import _build_step_mapping
    from app.services.script_pipeline import AssertionPlan

    m = _build_step_mapping(
        [_make_action()],
        [AssertionPlan(step=1, assertion_type="visible", target="账号输入框", expected=None, is_valid=True)],
        "#zh")
    row = m[0]
    assert row["element_id"] == "el-1"
    assert row["match_level"] == "L2"
    assert row["match_score"] == 0.82
    assert row["element_name"] == "账号输入框"


@pytest.mark.asyncio
async def test_step3_miss_stays_draft_no_ai():
    results = await step3_match_locators(
        [_act(1, "fill", "不存在的东西", "x")], "p1",
        lookup=FakeCandidates({}), ai_optimize=False, gateway=None)
    r = results[0]
    assert r.locator_status == "none_draft"
    assert r.locator is None


@pytest.mark.asyncio
async def test_step3_l3_ai_pick_from_candidates():
    """L3：未命中+ai_optimize → 候选清单给 LLM 单选，不生成定位器。"""
    cands = {("神秘控件", "click"): [
        {"element_id": "el-a", "element_name": "按钮A", "locator": "#a", "confidence": 3, "score": 0.3, "match_level": "low"},
        {"element_id": "el-b", "element_name": "按钮B", "locator": "#b", "confidence": 3, "score": 0.2, "match_level": "low"},
    ]}
    gw = FakeGateway(pick=1)
    results = await step3_match_locators(
        [_act(1, "click", "神秘控件")], "p1",
        lookup=FakeCandidates(cands), ai_optimize=True, gateway=gw)
    r = results[0]
    assert r.locator == "#b"
    assert r.locator_status == "pending_confirm"
    assert r.element_id == "el-b"
    # prompt 里只含候选清单，不含"生成定位器"
    prompt_text = str(gw.calls[0])
    assert "按钮B" in prompt_text


@pytest.mark.asyncio
async def test_step3_l3_invalid_pick_falls_to_draft():
    cands = {("神秘控件", "click"): [
        {"element_id": "el-a", "element_name": "按钮A", "locator": "#a", "confidence": 3, "score": 0.3, "match_level": "low"}]}
    gw = FakeGateway(pick=99)  # 越界
    results = await step3_match_locators(
        [_act(1, "click", "神秘控件")], "p1",
        lookup=FakeCandidates(cands), ai_optimize=True, gateway=gw)
    assert results[0].locator_status == "none_draft"
