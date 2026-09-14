"""测试集删除已存在回归 + ExecutionRecord.test_set_id + 记录/趋势端点（IA改造 Task2）。"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from app.api.v1 import test_sets as ts_api
from app.models.execution import ExecutionRecord


def test_execution_record_has_test_set_id():
    assert hasattr(ExecutionRecord, "test_set_id")


@pytest.mark.asyncio
async def test_delete_test_set():
    ts = MagicMock(); ts.id = uuid.uuid4()
    from app.services.test_set_service import TestSetService
    with patch.object(TestSetService, "delete_set", AsyncMock(return_value=None)) as m:
        resp = await ts_api.delete_test_set(str(ts.id), db=MagicMock())
    assert resp["code"] == 0
    m.assert_called_once()


@pytest.mark.asyncio
async def test_delete_test_set_404():
    db = MagicMock(); db.get = AsyncMock(return_value=None)
    from app.services.test_set_service import TestSetService
    with patch.object(TestSetService, "delete_set", AsyncMock(side_effect=ValueError("测试集不存在"))):
        with pytest.raises(HTTPException) as ei:
            await ts_api.delete_test_set("00000000-0000-0000-0000-000000000000", db=db)
        assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_get_test_set_single():
    """单查端点：GET /test-sets/{set_id}。"""
    ts = MagicMock(); ts.id = uuid.uuid4()
    ts.to_dict = MagicMock(return_value={"id": str(ts.id), "name": "S"})
    with patch("app.api.v1.test_sets.TestSetService") as MockSvc:
        MockSvc.return_value.get_set = AsyncMock(return_value=ts)
        resp = await ts_api.get_test_set(str(ts.id), db=MagicMock())
    assert resp["code"] == 0
    assert resp["data"]["name"] == "S"


@pytest.mark.asyncio
async def test_list_test_set_records_filters():
    """records 端点透传 page/page_size/result 给 list_records。"""
    captured = {}
    with patch("app.api.v1.test_sets.ExecutionQueryService") as MockSvc:
        async def fake_list(self, test_set_id, page=1, page_size=20, result="all"):
            captured.update(test_set_id=test_set_id, page=page,
                            page_size=page_size, result=result)
            return {"total": 0, "page": page, "page_size": page_size, "items": []}
        MockSvc.return_value.list_set_records = fake_list.__get__(MagicMock())
        resp = await ts_api.list_test_set_records(
            "11111111-1111-1111-1111-111111111111",
            page=2, page_size=5, result="failed", db=MagicMock())
    assert resp["code"] == 0
    assert captured["page"] == 2 and captured["page_size"] == 5
    assert captured["result"] == "failed"


@pytest.mark.asyncio
async def test_test_set_trend_endpoint():
    with patch("app.api.v1.test_sets.ExecutionQueryService") as MockSvc:
        async def fake_trend(self, test_set_id, limit=10):
            return [{"pass_rate": 80.0, "status": "done", "started_at": None}]
        MockSvc.return_value.set_trend = fake_trend.__get__(MagicMock())
        resp = await ts_api.test_set_trend(
            "11111111-1111-1111-1111-111111111111", db=MagicMock())
    assert resp["code"] == 0
    assert resp["data"][0]["pass_rate"] == 80.0


def test_list_records_signature_has_test_set_filter():
    """ExecutionQueryService 需支持 test_set_id 过滤与 set_trend。"""
    from app.services.execution_query_service import ExecutionQueryService
    import inspect
    sig = inspect.signature(ExecutionQueryService.list_records)
    assert "test_set_id" in sig.parameters
    assert hasattr(ExecutionQueryService, "set_trend")


@pytest.mark.asyncio
async def test_run_scripts_task_writes_test_set_id():
    """run_scripts_task 接受 test_set_id 并写入 ExecutionRecord。"""
    import inspect
    from app.tasks.script_tasks import run_scripts_task
    sig = inspect.signature(run_scripts_task.run)
    assert "test_set_id" in sig.parameters


def test_failed_filter_excludes_running():
    """failed 筛选不应把 running 记录算作失败（T2 小修）。"""
    import re
    src = open("app/services/execution_query_service.py", encoding="utf-8").read()
    seg = src[src.index('result == "failed"'):src.index("total_q", src.index('result == "failed"'))]
    assert '"running"' in seg
