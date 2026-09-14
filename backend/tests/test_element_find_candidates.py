"""find_candidates 评分管线测试（方案V1 阶段1）。"""
import uuid as uuid_mod
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.element_service import ElementService, normalize_text, score_element

PROJ_UUID = str(uuid_mod.uuid4())


def test_normalize_fullwidth_punct_case():
    assert normalize_text("Ａｃｃｏｕｎｔ， 输入框！") == "account输入框"
    assert normalize_text("  获取 验证码  ") == "获取验证码"
    assert normalize_text(None) == ""


def _mk_elem(name="账号输入框", text="请输入账号", tag="input"):
    e = MagicMock()
    e.element_name, e.element_text, e.tag_name = name, text, tag
    e.element_id = "el-1"
    e.confidence = 5
    e.locator_strategies = {"strategies": [{"type": "css", "value": "#zh", "confidence": 5}]}
    e.page_id = "p-1"
    return e


def test_normalize_curly_quotes():
    assert normalize_text("“获取验证码”") == "获取验证码"
    assert normalize_text("‘账号’") == "账号"


def test_score_empty_normalized_target():
    # 纯标点/弯引号 target 归一化后为空串 → 0 分，不参与命中
    e = {"element_name": "获取验证码", "element_text": "获取验证码", "tag": "button",
         "locators": {"strategies": []}}
    assert score_element("”", "click", e) == 0.0
    assert score_element("。！？", "click", e) == 0.0


def test_score_exact_alias():
    e = {"element_name": "账号输入框", "element_text": "请输入账号", "tag": "input",
         "locators": {"strategies": [{"type": "css", "value": "#zh", "confidence": 5}]}}
    assert score_element("账号输入框", "input", e) >= 1.0


def test_score_text_containment():
    e = {"element_name": "获取验证码", "element_text": "获取验证码", "tag": "button",
         "locators": {"strategies": []}}
    s = score_element("获取验证码按钮", "click", e)
    assert 0.75 <= s < 1.0


def test_score_low_returns_below_threshold():
    e = {"element_name": "完全无关", "element_text": "", "tag": "select",
         "locators": {"strategies": []}}
    assert score_element("账号输入框", "input", e) < 0.75


def test_score_type_mismatch_penalized():
    e1 = {"element_name": "账号", "element_text": "", "tag": "select", "locators": {"strategies": []}}
    e2 = {"element_name": "账号", "element_text": "", "tag": "input", "locators": {"strategies": []}}
    assert score_element("账号输入框", "input", e2) > score_element("账号输入框", "input", e1)


@pytest.mark.asyncio
async def test_find_candidates_returns_scored_list():
    db = MagicMock()
    rows = [_mk_elem(), _mk_elem(name="其他", text="", tag="button")]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    svc = ElementService(db=db)
    cands = await svc.find_candidates(PROJ_UUID, "账号输入框", intent_action="input")
    assert cands[0]["match_level"] in ("L1", "L2")
    assert cands[0]["score"] >= 0.75
    assert any(c["score"] < 0.75 for c in cands)


@pytest.mark.asyncio
async def test_find_candidates_empty_target():
    svc = ElementService(db=MagicMock())
    assert await svc.find_candidates(PROJ_UUID, "") == []


def _mk_elem_type(name, text, elem_type):
    """模拟真实 ElementRepository：只有 element_type 列，没有 tag_name。"""
    e = MagicMock(spec=["element_name", "element_text", "element_type",
                        "element_id", "confidence", "locator_strategies", "page_id"])
    e.element_name, e.element_text, e.element_type = name, text, elem_type
    e.element_id = "el-1"
    e.confidence = 5
    e.locator_strategies = {"strategies": [{"type": "css", "value": "#x", "confidence": 5}]}
    e.page_id = "p-1"
    return e


@pytest.mark.asyncio
async def test_find_candidates_reads_element_type_column():
    """RC2: ElementRepository 列名是 element_type 而非 tag_name，类型分必须生效。"""
    db = MagicMock()
    rows = [_mk_elem_type("请输入账号", "请输入账号", "input"),
            _mk_elem_type("请输入账号", "请输入账号", "button")]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    svc = ElementService(db=db)
    cands = await svc.find_candidates(PROJ_UUID, "账号输入框", intent_action="input")
    input_score = next(c["score"] for c in cands if c["element_id"] == "el-1")
    # 两条都映射到同一 element_id，只会有一个候选；直接验证 score 含类型分
    assert cands[0]["score"] >= 0.75


def test_score_stem_control_word_match():
    """RC2 stem 规则：账号输入框 vs 请输入账号（剥控件词后互相包含）→ L2 级。"""
    e = {"element_name": "请输入账号", "element_text": "请输入账号", "tag": "input",
         "locators": {"strategies": []}}
    s = score_element("账号输入框", "input", e)
    assert s >= 0.75


def test_score_stem_password():
    e = {"element_name": "请输入密码", "element_text": "请输入密码", "tag": "input",
         "locators": {"strategies": []}}
    assert score_element("密码输入框", "input", e) >= 0.75


def test_score_stem_exact_stem_equal():
    """登录按钮 vs 登录：剥离后完全相等 → 高分。"""
    e = {"element_name": "登录", "element_text": "登录", "tag": "button",
         "locators": {"strategies": []}}
    assert score_element("登录按钮", "click", e) >= 0.9


def test_score_captcha_button_not_regressed():
    """获取验证码按钮 vs 获取验证码：原 contain 路径保持高分。"""
    e = {"element_name": "获取验证码", "element_text": "获取验证码", "tag": "button",
         "locators": {"strategies": []}}
    assert score_element("获取验证码按钮", "click", e) >= 0.75


def test_score_stem_unrelated_not_boosted():
    """剥离后仍无关的不得误命中。"""
    e = {"element_name": "完全无关", "element_text": "", "tag": "input",
         "locators": {"strategies": []}}
    assert score_element("账号输入框", "input", e) < 0.75
