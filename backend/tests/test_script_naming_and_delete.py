"""脚本名改用例名 + 脚本删除端点（IA改造 Task1）。"""
import uuid
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.services.batch_naming import build_script_name
from app.api.v1 import scripts as scripts_api


# --- 命名：用例名优先 ---

TS = datetime(2026, 9, 14, 10, 0, 0)


def test_build_script_name_case_title_first():
    """用例名优先：不再拼 批次名-自动化脚本HHmmss。"""
    name = build_script_name("批次A", "登录功能验证", TS, taken=set())
    assert name == "登录功能验证"


def test_build_script_name_collision_suffix():
    name = build_script_name("批次A", "登录功能验证", TS, taken={"登录功能验证"})
    assert name == "登录功能验证-2"
    name2 = build_script_name(
        "批次A", "登录功能验证", TS,
        taken={"登录功能验证", "登录功能验证-2"})
    assert name2 == "登录功能验证-3"


def test_build_script_name_empty_title_fallback():
    name = build_script_name("批次A", "", TS, taken=set())
    assert "自动化脚本" in name  # 无用例名回退批次名风格


def test_build_script_name_no_batch_no_title():
    name = build_script_name(None, None, TS, taken=set())
    assert "自动化脚本" in name


# --- 删除端点（直调风格） ---


@pytest.mark.asyncio
async def test_delete_script_soft():
    """DELETE /scripts/{id} → 软删 is_deleted=True，不 db.delete。"""
    asset = MagicMock()
    asset.is_deleted = False
    db = MagicMock()
    db.get = AsyncMock(return_value=asset)
    db.commit = AsyncMock()
    sid = str(uuid.uuid4())
    resp = await scripts_api.delete_script(sid, db=db)
    assert resp["code"] == 0
    assert asset.is_deleted is True
    db.delete.assert_not_called()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_script_404():
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as ei:
        await scripts_api.delete_script(
            "00000000-0000-0000-0000-000000000000", db=db)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_script_bad_uuid():
    db = MagicMock()
    with pytest.raises(HTTPException) as ei:
        await scripts_api.delete_script("not-a-uuid", db=db)
    assert ei.value.status_code == 400
