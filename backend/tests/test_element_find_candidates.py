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
