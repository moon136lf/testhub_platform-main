"""script_steps 表 + 保存落库 + 人工绑定回写 synonym（方案V1 阶段4）。"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.script_step import ScriptStep
from app.services.script_edit_service import ScriptEditService


def _mock_db(asset):
    db = MagicMock()
    db.get = AsyncMock(return_value=asset)
    db.execute = AsyncMock()
    db.add_all = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_save_steps_persists_script_step_rows():
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.name = "登录脚本"
    asset.version = 1
    svc = ScriptEditService(db=_mock_db(asset))
    el_uuid = str(uuid.uuid4())
    steps = [{
        "seq": 1, "action": "input", "target": "#zh", "value": "test02",
        "element_name": "请输入账号", "expected": "显示test02",
        "element_id": el_uuid, "case_step_no": 2, "assertion_type": "expect_text",
    }]
    saved = await svc.save_steps(str(asset.id), "登录脚本", steps)
    assert saved is asset
    rows = svc.db.add_all.call_args[0][0]
    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r, ScriptStep)
    assert r.element_id == uuid.UUID(el_uuid)  # FK→element_repository.id(UUID)
    assert r.case_step_no == 2
    assert r.assertion == "显示test02"
    assert r.assertion_type == "expect_text"
    assert r.step_no == 1


@pytest.mark.asyncio
async def test_save_steps_invalid_element_id_becomes_none():
    """element_id 非 UUID（脏数据）→ 置 None，不阻断保存。"""
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.name = "t"
    svc = ScriptEditService(db=_mock_db(asset))
    steps = [{"seq": 1, "action": "click", "target": "#b", "value": "",
              "element_name": "b", "expected": "", "element_id": "el-1"}]
    await svc.save_steps(str(asset.id), "t", steps)
    r = svc.db.add_all.call_args[0][0][0]
    assert r.element_id is None


@pytest.mark.asyncio
async def test_save_steps_replaces_old_rows():
    """先删后插全量替换：保存前执行 delete。"""
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.name = "t"
    db = _mock_db(asset)
    svc = ScriptEditService(db=db)
    steps = [{"seq": 1, "action": "navigate", "target": "", "value": "https://x", "element_name": ""}]
    await svc.save_steps(str(asset.id), "t", steps)
    assert db.execute.await_count == 1  # sa_delete(ScriptStep)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_binding_writes_synonym():
    """人工绑定（element_id + case_target_text）→ 回写 synonym(source=manual_binding)。"""
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.name = "t"
    svc = ScriptEditService(db=_mock_db(asset))
    svc.write_synonym = AsyncMock(return_value=True)
    steps = [{"seq": 1, "action": "click", "target": "#login", "value": "",
              "element_name": "登录按钮", "expected": "",
              "element_id": str(uuid.uuid4()), "case_step_no": 5,
              "case_target_text": "确定登录的按钮"}]
    await svc.save_steps(str(asset.id), "t", steps)
    svc.write_synonym.assert_awaited_once()
    args, kwargs = svc.write_synonym.await_args
    assert kwargs.get("source") == "manual_binding"
    assert args[1] == "确定登录的按钮"


@pytest.mark.asyncio
async def test_synonym_write_failure_does_not_block_save():
    """synonym 回写异常不阻断保存。"""
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.name = "t"
    svc = ScriptEditService(db=_mock_db(asset))
    svc.write_synonym = AsyncMock(side_effect=RuntimeError("boom"))
    steps = [{"seq": 1, "action": "click", "target": "#login", "value": "",
              "element_name": "b", "expected": "",
              "element_id": str(uuid.uuid4()), "case_target_text": "x"}]
    saved = await svc.save_steps(str(asset.id), "t", steps)
    assert saved is asset


@pytest.mark.asyncio
async def test_no_synonym_without_target_text():
    """无 case_target_text → 不回写。"""
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.name = "t"
    svc = ScriptEditService(db=_mock_db(asset))
    svc.write_synonym = AsyncMock(return_value=True)
    steps = [{"seq": 1, "action": "click", "target": "#login", "value": "",
              "element_name": "b", "expected": "", "element_id": str(uuid.uuid4())}]
    await svc.save_steps(str(asset.id), "t", steps)
    svc.write_synonym.assert_not_awaited()
