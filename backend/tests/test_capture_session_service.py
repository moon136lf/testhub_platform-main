# -*- coding: utf-8 -*-
"""P3 会话式抓取工作台 - CaptureSessionService 单元测试（fakeredis 桩）"""

import pytest
from unittest.mock import patch

from app.services.capture_session_service import CaptureSessionService


class FakeAsyncRedis:
    """内存版 async redis 桩（set/get/delete 与 redis_client 接口一致）"""

    def __init__(self):
        self._data = {}

    async def set(self, key, value, ex=None):
        self._data[key] = value

    async def get(self, key):
        return self._data.get(key)

    async def delete(self, key):
        self._data.pop(key, None)


@pytest.fixture
def patch_redis():
    client = FakeAsyncRedis()
    with patch("app.services.capture_session_service.redis_client", client):
        yield client


@pytest.mark.asyncio
async def test_create_and_get_session(patch_redis):
    state = await CaptureSessionService.create("proj-1")
    assert state["session_id"].startswith("cap_")
    loaded = await CaptureSessionService.get(state["session_id"])
    assert loaded["project_id"] == "proj-1"
    assert loaded["elements"] == {}


@pytest.mark.asyncio
async def test_get_missing_session(patch_redis):
    assert await CaptureSessionService.get("cap_missing") is None


@pytest.mark.asyncio
async def test_add_batch_and_select(patch_redis):
    s = await CaptureSessionService.create("proj-1")
    sid = s["session_id"]
    elements = [
        {"temp_id": "t1", "element_type": "button", "element_text": "登录",
         "locator_strategies": {"strategies": []}, "semantic_info": {}},
        {"temp_id": "t2", "element_type": "input", "element_text": "",
         "locator_strategies": {"strategies": []}, "semantic_info": {}},
    ]
    r = await CaptureSessionService.add_batch(sid, "http://x/", "shot.png", elements)
    assert r["added"] == 2 and r["batch_idx"] == 0 and r["total_elements"] == 2

    # 默认全选
    sel = await CaptureSessionService.get_selected_elements(sid)
    assert sel["total_selected"] == 2

    # 取消 t1
    assert await CaptureSessionService.set_element_included(sid, "t1", False)
    sel = await CaptureSessionService.get_selected_elements(sid)
    assert sel["total_selected"] == 1 and sel["elements"][0]["temp_id"] == "t2"


@pytest.mark.asyncio
async def test_set_all_included(patch_redis):
    s = await CaptureSessionService.create("p")
    sid = s["session_id"]
    await CaptureSessionService.add_batch(sid, "u", "", [
        {"temp_id": f"t{i}", "element_type": "button", "element_text": "",
         "locator_strategies": {"strategies": []}, "semantic_info": {}} for i in range(3)
    ])
    await CaptureSessionService.set_all_included(sid, False)
    sel = await CaptureSessionService.get_selected_elements(sid)
    assert sel["total_selected"] == 0
    count = await CaptureSessionService.set_all_included(sid, True)
    assert count == 3


@pytest.mark.asyncio
async def test_delete_element(patch_redis):
    s = await CaptureSessionService.create("p")
    sid = s["session_id"]
    await CaptureSessionService.add_batch(sid, "u", "", [
        {"temp_id": "t1", "element_type": "button", "element_text": "",
         "locator_strategies": {"strategies": []}, "semantic_info": {}},
    ])
    assert await CaptureSessionService.delete_element(sid, "t1")
    state = await CaptureSessionService.get(sid)
    assert state["elements"] == {}
    assert state["batches"][0]["temp_ids"] == []
    assert not await CaptureSessionService.delete_element(sid, "t1")  # 已不存在


@pytest.mark.asyncio
async def test_remove_batch(patch_redis):
    s = await CaptureSessionService.create("p")
    sid = s["session_id"]
    for i in range(2):
        await CaptureSessionService.add_batch(sid, f"u{i}", "", [
            {"temp_id": f"b{i}t{j}", "element_type": "button", "element_text": "",
             "locator_strategies": {"strategies": []}, "semantic_info": {}}
            for j in range(2)
        ])
    removed = await CaptureSessionService.remove_batch(sid, 0)
    assert removed == 2
    state = await CaptureSessionService.get(sid)
    assert set(state["elements"].keys()) == {"b1t0", "b1t1"}
    assert state["batches"][0]["removed"] is True
    # 重复删除返回 0
    assert await CaptureSessionService.remove_batch(sid, 0) == 0


@pytest.mark.asyncio
async def test_batch_limit(patch_redis):
    s = await CaptureSessionService.create("p")
    sid = s["session_id"]
    from app.services.capture_session_service import MAX_BATCHES
    for _ in range(MAX_BATCHES):
        await CaptureSessionService.add_batch(sid, "u", "", [])
    with pytest.raises(ValueError):
        await CaptureSessionService.add_batch(sid, "u", "", [])


@pytest.mark.asyncio
async def test_delete_session(patch_redis):
    s = await CaptureSessionService.create("p")
    sid = s["session_id"]
    assert await CaptureSessionService.delete(sid)
    assert await CaptureSessionService.get(sid) is None
    assert not await CaptureSessionService.delete(sid)
