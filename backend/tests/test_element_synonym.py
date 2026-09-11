"""element_synonyms 表 + 回写 + find_candidates synonym 优先命中（方案V1 阶段2）。"""
import uuid as uuid_mod
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models.element import ElementSynonym
from app.services.element_service import ElementService

PROJ_UUID = str(uuid_mod.uuid4())


@pytest.mark.asyncio
async def test_write_synonym_inserts():
    svc = ElementService(db=MagicMock())
    empty = MagicMock(scalars=MagicMock(all=MagicMock(return_value=[])))
    svc.db.execute = AsyncMock(return_value=empty)
    svc.db.add = MagicMock()
    svc.db.flush = AsyncMock()
    ok = await svc.write_synonym("el-1", "账号输入框", source="manual_binding")
    assert ok
    svc.db.add.assert_called_once()
    syn = svc.db.add.call_args[0][0]
    assert isinstance(syn, ElementSynonym)
    assert syn.synonym_text == "账号输入框"
    assert syn.source == "manual_binding"


@pytest.mark.asyncio
async def test_write_synonym_dedup():
    """同 element+text（归一化比对）已存在 → 不重复插入。"""
    svc = ElementService(db=MagicMock())
    svc.db.flush = AsyncMock()
    existing = MagicMock(spec=ElementSynonym)
    existing.synonym_text = "账号输入框"
    result = MagicMock()
    result.scalars.return_value.all.return_value = [existing]
    svc.db.execute = AsyncMock(return_value=result)
    ok = await svc.write_synonym("el-1", "账号输入框")
    assert ok
    svc.db.add.assert_not_called()


def _mk_elem(name="输入框1", text="", tag="input"):
    e = MagicMock()
    e.element_name, e.element_text, e.tag_name = name, text, tag
    e.element_id = "el-1"
    e.confidence = 5
    e.locator_strategies = {"strategies": [{"type": "css", "value": "#zh", "confidence": 5}]}
    e.page_id = "p-1"
    return e


@pytest.mark.asyncio
async def test_find_candidates_synonym_hit_high_score():
    """synonym 表命中（归一化相等）→ score=0.9, level=L2。"""
    svc = ElementService(db=MagicMock())
    syn = MagicMock()
    syn.element_id = "el-1"
    syn.synonym_text = "账号输入框"
    # 第一次 execute 返回 synonym 行，第二次返回元素全量
    elem = _mk_elem()  # 别名与目标差很远，仅靠 synonym 命中
    syn_result = MagicMock()
    syn_result.scalars.return_value.all.return_value = [syn]
    elem_result = MagicMock()
    elem_result.scalars.return_value.all.return_value = [elem]
    svc.db.execute = AsyncMock(side_effect=[syn_result, elem_result])
    cands = await svc.find_candidates(PROJ_UUID, "账号输入框", intent_action="input")
    top = cands[0]
    assert top["element_id"] == "el-1"
    assert top["match_level"] == "L2"
    assert 0.85 <= top["score"] <= 0.95


@pytest.mark.asyncio
async def test_find_candidates_no_synonym_query_fallback():
    """synonym 查询异常/无命中 → 走普通评分，不抛错。"""
    db = MagicMock()
    rows = [_mk_elem(name="账号输入框", text="请输入账号")]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    svc = ElementService(db=db)
    cands = await svc.find_candidates(PROJ_UUID, "账号输入框", intent_action="input")
    assert cands[0]["match_level"] == "L1"
    assert cands[0]["score"] >= 1.0
