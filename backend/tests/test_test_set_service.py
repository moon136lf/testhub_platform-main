"""TestSetService 测试（mock db）"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

from app.services.test_set_service import TestSetService


def _db():
    db = MagicMock()
    db.commit = AsyncMock()

    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = []
        r.scalar_one_or_none.return_value = None
        return r
    db.execute = _execute
    return db


def _exec(rows):
    async def _execute(q):
        r = MagicMock()
        r.scalars.return_value.all.return_value = rows
        return r
    return _execute


class TestCrud:
    @pytest.mark.asyncio
    async def test_create_with_case_ids(self):
        db = _db()
        added = []
        db.add = lambda o: added.append(o)
        db.flush = AsyncMock()

        svc = TestSetService(db)
        ts = await svc.create_set("p1", "冒烟集", ["c1", "c2"], source="convert_page")
        assert added[0].name == "冒烟集"
        assert added[0].case_ids == ["c1", "c2"]
        assert added[0].source == "convert_page"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_empty_name_raises(self):
        svc = TestSetService(_db())
        with pytest.raises(ValueError, match="名称"):
            await svc.create_set("p1", "  ", ["c1"])

    @pytest.mark.asyncio
    async def test_create_empty_cases_raises(self):
        svc = TestSetService(_db())
        with pytest.raises(ValueError, match="用例"):
            await svc.create_set("p1", "x", [])

    @pytest.mark.asyncio
    async def test_create_duplicate_name_raises(self):
        """同项目重名（唯一约束）——service 层查重抛错（比等 DB 约束报错友好）"""
        db = _db()

        async def _execute(q):
            r = MagicMock()
            r.scalar_one_or_none.return_value = MagicMock()  # 已存在同名
            return r
        db.execute = _execute

        svc = TestSetService(db)
        with pytest.raises(ValueError, match="已存在"):
            await svc.create_set("p1", "冒烟集", ["c1"])

    @pytest.mark.asyncio
    async def test_update_name_and_description(self):
        db = _db()
        ts = MagicMock()
        ts.name = "旧名"

        async def _get(cls, sid):
            return ts
        db.get = _get

        svc = TestSetService(db)
        await svc.update_set(str(uuid4()), {"name": "新名", "description": "描述"})
        assert ts.name == "新名"
        assert ts.description == "描述"

    @pytest.mark.asyncio
    async def test_update_unknown_field_raises(self):
        db = _db()
        ts = MagicMock()
        async def _get(cls, sid):
            return ts
        db.get = _get
        svc = TestSetService(db)
        with pytest.raises(ValueError, match="不可"):
            await svc.update_set(str(uuid4()), {"hack": 1})

    @pytest.mark.asyncio
    async def test_delete_set(self):
        db = _db()
        ts = MagicMock()
        async def _get(cls, sid):
            return ts
        db.get = _get
        db.delete = AsyncMock()

        svc = TestSetService(db)
        await svc.delete_set(str(uuid4()))
        db.delete.assert_awaited_once_with(ts)

    @pytest.mark.asyncio
    async def test_list_by_project(self):
        db = _db()
        rows = [MagicMock(), MagicMock()]
        db.execute = _exec(rows)
        svc = TestSetService(db)
        out = await svc.list_sets("p1")
        assert out == rows


class TestCaseManagement:
    @pytest.mark.asyncio
    async def test_add_cases_merges_dedup(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1"]

        async def _get(cls, sid):
            return ts
        db.get = _get

        svc = TestSetService(db)
        await svc.add_cases(str(uuid4()), ["c2", "c1"])
        assert sorted(ts.case_ids) == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_remove_case(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1", "c2"]

        async def _get(cls, sid):
            return ts
        db.get = _get

        svc = TestSetService(db)
        await svc.remove_case(str(uuid4()), "c1")
        assert ts.case_ids == ["c2"]

    @pytest.mark.asyncio
    async def test_remove_missing_case_noop(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["c1"]
        async def _get(cls, sid):
            return ts
        db.get = _get
        svc = TestSetService(db)
        await svc.remove_case(str(uuid4()), "nope")
        assert ts.case_ids == ["c1"]


class TestExecution:
    @pytest.mark.asyncio
    async def test_run_resolves_cases_to_latest_scripts(self):
        """执行：case_ids → 查 ScriptAsset（每 case 取最新）→ run_scripts_task.delay"""
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]
        ts.name = "冒烟集"
        ts.status = "pending"

        async def _get(cls, sid):
            return ts
        s1, s2 = MagicMock(id=uuid4()), MagicMock(id=uuid4())
        s1.case_id, s2.case_id = ts.case_ids[0], ts.case_ids[1]

        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [s1, s2]
            return r
        db.get = _get
        db.execute = _execute

        with patch("app.services.test_set_service.run_scripts_task") as mock_task:
            mock_task.delay.return_value = MagicMock(id="task-1")
            svc = TestSetService(db)
            result = await svc.run_set(str(uuid4()), headless=True, fail_fast=False)
            assert result["script_count"] == 2
            assert "session_id" in result and "sse_url" in result
            mock_task.delay.assert_called_once()
            kwargs = mock_task.delay.call_args.kwargs
            assert kwargs.get("exec_type") == "ui_testset"
            assert ts.status == "running"
            # last_exec_id 与 run_scripts_task 的 exec_id 规则一致
            assert ts.last_exec_id == f"exec-{result['session_id'][:8]}"

    @pytest.mark.asyncio
    async def test_run_empty_scripts_raises(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["11111111-1111-1111-1111-111111111111"]
        async def _get(cls, sid):
            return ts
        async def _execute(q):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r
        db.get = _get
        db.execute = _execute
        svc = TestSetService(db)
        with pytest.raises(ValueError, match="脚本"):
            await svc.run_set(str(uuid4()))

    @pytest.mark.asyncio
    async def test_run_empty_set_raises(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = []
        async def _get(cls, sid):
            return ts
        db.get = _get
        svc = TestSetService(db)
        with pytest.raises(ValueError, match="空"):
            await svc.run_set(str(uuid4()))

    @pytest.mark.asyncio
    async def test_missing_case_ids_no_scripts_raises(self):
        db = _db()
        ts = MagicMock()
        ts.case_ids = ["not-a-uuid"]  # 非法 case_id → 解析失败 → 空脚本
        async def _get(cls, sid):
            return ts
        db.get = _get
        svc = TestSetService(db)
        with pytest.raises(ValueError):
            await svc.run_set(str(uuid4()))


class TestReport:
    @pytest.mark.asyncio
    async def test_report_aggregates_record_and_details(self):
        db = _db()
        ts = MagicMock()
        ts.last_exec_id = "exec-abc123"
        ts.last_pass_rate = 80.0

        async def _get(cls, sid):
            return ts
        er = MagicMock(exec_id="exec-abc123", status="done", total_cases=5,
                       passed_count=4, fail_count=1, pass_rate=80.0, duration_ms=3000)
        d1 = MagicMock(status="fail", error_type="assertion_failed",
                       screenshot_url="http://minio/s.png", duration_ms=1200)
        d2 = MagicMock(status="pass", error_type=None, screenshot_url=None, duration_ms=800)

        state = {"n": 0}
        async def _execute(q):
            state["n"] += 1
            r = MagicMock()
            if state["n"] == 1:
                r.scalar_one_or_none.return_value = er
            else:
                r.scalars.return_value.all.return_value = [d1, d2]
            return r
        db.get = _get
        db.execute = _execute

        svc = TestSetService(db)
        report = await svc.get_report(str(uuid4()))
        assert report["record"]["exec_id"] == "exec-abc123"
        assert report["pass_rate"] == 80.0
        assert len(report["details"]) == 2
        assert report["details"][0]["screenshot_url"] == "http://minio/s.png"

    @pytest.mark.asyncio
    async def test_report_no_execution_returns_empty(self):
        db = _db()
        ts = MagicMock()
        ts.last_exec_id = None
        async def _get(cls, sid):
            return ts
        db.get = _get
        svc = TestSetService(db)
        assert await svc.get_report(str(uuid4())) is None

    @pytest.mark.asyncio
    async def test_run_fail_fast_sets_max_failures(self):
        """fail_fast=True → max_failures=1（执行器 `0 or 8` 回落为 8，故用 1）；False → 100"""
        for fail_fast, expected in [(True, 1), (False, 100)]:
            db = _db()
            ts = MagicMock()
            ts.case_ids = ["11111111-1111-1111-1111-111111111111"]
            async def _get(cls, sid):
                return ts
            s1 = MagicMock(id=uuid4())
            s1.case_id = ts.case_ids[0]
            async def _execute(q):
                r = MagicMock()
                r.scalars.return_value.all.return_value = [s1]
                return r
            db.get = _get
            db.execute = _execute

            with patch("app.services.test_set_service.run_scripts_task") as mock_task:
                mock_task.delay.return_value = MagicMock(id="t")
                await TestSetService(db).run_set(str(uuid4()), fail_fast=fail_fast)
                config = mock_task.delay.call_args.kwargs["config"]
                assert config["max_failures"] == expected
                assert config["fail_fast"] == fail_fast
