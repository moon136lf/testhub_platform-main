"""
Script conversion API tests (模块 #4, Task 13).

Mirrors the repo convention from test_api_ai_case_generation.py: call the
endpoint function directly with an AsyncMock db session and patch the Celery
task — no ASGI client, no real DB, no dependency_overrides.
"""

import sys
from pathlib import Path
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from fastapi import HTTPException

# Add backend directory to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))


def asyncio_run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mock_db():
    """Mock async database session (mirrors ai_case_generation test fixture)."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def sample_project_id():
    return str(uuid4())


class TestConvertScriptsEndpoint:
    """Test POST /api/v1/scripts/convert"""

    @pytest.mark.asyncio
    async def test_convert_returns_session_id(self, mock_db, sample_project_id):
        """Project exists + finalized case exists -> 200 + session_id + sse_url."""
        from app.api.v1.scripts import convert_scripts
        from app.schemas.script import ConvertRequest

        case_ids = [str(uuid4())]

        # 1st execute -> project exists; 2nd execute -> finalized case found
        mock_project = MagicMock()
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none = MagicMock(return_value=mock_project)

        mock_case = MagicMock()
        mock_result_cases = MagicMock()
        mock_result_cases.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[mock_case]))
        )

        mock_db.execute.side_effect = [mock_result_project, mock_result_cases]

        # Stub the Celery task so no broker is hit
        with patch("app.api.v1.scripts.convert_scripts_task") as mock_task:
            mock_task.delay = MagicMock()

            request = ConvertRequest(
                project_id=sample_project_id,
                case_ids=case_ids,
                ai_optimize=False,
            )
            response = await convert_scripts(request, mock_db)

        assert response["code"] == 0
        assert "session_id" in response["data"]
        assert "sse_url" in response["data"]
        assert response["data"]["sse_url"].startswith("/api/sse/stream/")
        mock_task.delay.assert_called_once()
        # task.delay must be called with the request's project/case ids + ai_optimize
        _, kwargs = mock_task.delay.call_args
        assert kwargs["project_id"] == sample_project_id
        assert kwargs["case_ids"] == case_ids
        assert kwargs["ai_optimize"] is False

    @pytest.mark.asyncio
    async def test_convert_project_not_found(self, mock_db, sample_project_id):
        """Project missing -> 404."""
        from app.api.v1.scripts import convert_scripts
        from app.schemas.script import ConvertRequest

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_result

        request = ConvertRequest(
            project_id=sample_project_id,
            case_ids=[str(uuid4())],
            ai_optimize=False,
        )
        with pytest.raises(HTTPException) as exc_info:
            await convert_scripts(request, mock_db)

        assert exc_info.value.status_code == 404
        assert "Project not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_convert_no_finalized_cases(self, mock_db, sample_project_id):
        """No finalized cases -> 400."""
        from app.api.v1.scripts import convert_scripts
        from app.schemas.script import ConvertRequest

        mock_project = MagicMock()
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none = MagicMock(return_value=mock_project)

        mock_result_cases = MagicMock()
        mock_result_cases.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )

        mock_db.execute.side_effect = [mock_result_project, mock_result_cases]

        request = ConvertRequest(
            project_id=sample_project_id,
            case_ids=[str(uuid4())],
            ai_optimize=False,
        )
        with pytest.raises(HTTPException) as exc_info:
            await convert_scripts(request, mock_db)

        assert exc_info.value.status_code == 400
        assert "已定稿" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_convert_invalid_uuid(self, mock_db):
        """Invalid project_id UUID -> 400."""
        from app.api.v1.scripts import convert_scripts
        from app.schemas.script import ConvertRequest

        request = ConvertRequest(
            project_id="not-a-uuid",
            case_ids=[str(uuid4())],
            ai_optimize=False,
        )
        with pytest.raises(HTTPException) as exc_info:
            await convert_scripts(request, mock_db)

        assert exc_info.value.status_code == 400


class TestListScriptsEndpoint:
    """Test GET /api/v1/scripts"""

    @pytest.mark.asyncio
    async def test_list_returns_scripts(self, mock_db, sample_project_id):
        from app.api.v1.scripts import list_scripts

        mock_script = MagicMock()
        mock_script.to_dict = MagicMock(
            return_value={"id": str(uuid4()), "name": "login_test.py"}
        )
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[mock_script]))
        )
        mock_db.execute.return_value = mock_result

        response = await list_scripts(
            project_id=sample_project_id, case_id=None, page=1, page_size=20, db=mock_db
        )

        assert response["code"] == 0
        assert len(response["data"]) == 1
        assert response["data"][0]["name"] == "login_test.py"

    @pytest.mark.asyncio
    async def test_list_no_filters(self, mock_db):
        from app.api.v1.scripts import list_scripts

        mock_result = MagicMock()
        mock_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )
        mock_db.execute.return_value = mock_result

        response = await list_scripts(
            project_id=None, case_id=None, page=1, page_size=20, db=mock_db
        )

        assert response["code"] == 0
        assert response["data"] == []

    @pytest.mark.asyncio
    async def test_list_applies_pagination_offset_limit(self, mock_db):
        """page=2, page_size=1 -> stmt must carry limit + offset(1)."""
        from app.api.v1.scripts import list_scripts

        mock_result = MagicMock()
        mock_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )
        mock_db.execute.return_value = mock_result

        response = await list_scripts(None, None, page=2, page_size=1, db=mock_db)

        assert response["code"] == 0
        mock_db.execute.assert_awaited_once()
        stmt = mock_db.execute.await_args.args[0]
        # Compile to inspect clauses + bound params without a DB.
        compiled = stmt.compile()
        rendered = str(compiled).lower()
        assert "limit" in rendered
        assert "offset" in rendered
        # page=2, page_size=1 -> offset = (page-1)*page_size = 1; limit = page_size = 1
        params = compiled.construct_params()
        assert 1 in params.values()  # offset = 1 and limit = 1

    @pytest.mark.asyncio
    async def test_list_invalid_filter_uuid(self, mock_db):
        from app.api.v1.scripts import list_scripts

        with pytest.raises(HTTPException) as exc_info:
            await list_scripts("not-a-uuid", None, 1, 20, mock_db)

        assert exc_info.value.status_code == 400


class TestGetScriptEndpoint:
    """Test GET /api/v1/scripts/{script_id}"""

    @pytest.mark.asyncio
    async def test_get_returns_script(self, mock_db):
        from app.api.v1.scripts import get_script

        mock_script = MagicMock()
        mock_script.to_dict = MagicMock(
            return_value={"id": str(uuid4()), "name": "login_test.py"}
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_script)
        mock_db.execute.return_value = mock_result

        response = await get_script(str(uuid4()), mock_db)

        assert response["code"] == 0
        assert response["data"]["name"] == "login_test.py"

    @pytest.mark.asyncio
    async def test_get_not_found(self, mock_db):
        from app.api.v1.scripts import get_script

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await get_script(str(uuid4()), mock_db)

        assert exc_info.value.status_code == 404
        assert "Script not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_get_invalid_uuid(self, mock_db):
        from app.api.v1.scripts import get_script

        with pytest.raises(HTTPException) as exc_info:
            await get_script("not-a-uuid", mock_db)

        assert exc_info.value.status_code == 400


class TestConfirmScriptEndpoint:
    """Test PUT /api/v1/scripts/{script_id}/confirm (TRANS-02)"""

    @pytest.mark.asyncio
    async def test_confirm_sets_status_to_confirmed(self, mock_db):
        """Asset found -> status set to confirmed, committed, return shape."""
        from app.api.v1.scripts import confirm_script

        mock_asset = MagicMock()
        mock_asset.status = "generated"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_asset)
        mock_db.execute.return_value = mock_result

        sid = str(uuid4())
        response = await confirm_script(sid, mock_db)

        assert response["code"] == 0
        assert response["message"] == "Script confirmed"
        assert response["data"]["script_id"] == sid
        assert response["data"]["status"] == "confirmed"
        assert mock_asset.status == "confirmed"
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirm_not_found(self, mock_db):
        """Asset missing -> 404."""
        from app.api.v1.scripts import confirm_script

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await confirm_script(str(uuid4()), mock_db)

        assert exc_info.value.status_code == 404
        assert "Script not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_confirm_invalid_uuid(self, mock_db):
        """Invalid UUID -> 400."""
        from app.api.v1.scripts import confirm_script

        with pytest.raises(HTTPException) as exc_info:
            await confirm_script("not-a-uuid", mock_db)

        assert exc_info.value.status_code == 400


class TestDiagnoseScriptEndpoint:
    """Test POST /api/v1/scripts/{script_id}/diagnose"""

    @pytest.mark.asyncio
    async def test_diagnose_can_fix_returns_card_and_revised_script(self, mock_db, monkeypatch):
        """can_fix=True with revised_step -> diagnosis card + revised_script + version bump."""
        from app.api.v1 import scripts as scripts_api
        from app.api.v1.scripts import diagnose_script
        from app.schemas.script import DiagnoseRequest

        # Fake diagnose service that returns a can_fix card
        class FakeDiag:
            async def diagnose(self, **kw):
                return {
                    "category": "script_problem",
                    "can_fix": True,
                    "reason": "x",
                    "failed_step": kw.get("failed_step"),
                    "error_type": kw.get("error_type"),
                    "error_msg": kw.get("error_msg"),
                    "screenshot_url": None,
                    "revised_step": "new code",
                    "suggestion": "已重生成",
                }

        monkeypatch.setattr(scripts_api, "ScriptDiagnoseService", lambda gateway: FakeDiag())
        monkeypatch.setattr(scripts_api, "AIGateway", lambda: None)

        # #5c: use a real ScriptAsset (no DB needed) so the array-ized write path
        # (mode/created_at, history preserved) is exercised, not auto-mocked.
        from app.models.test_case import ScriptAsset
        mock_asset = ScriptAsset(content="original content", version=1, ai_diagnosis=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_asset)
        mock_db.execute.return_value = mock_result

        request = DiagnoseRequest(
            error_type="locate_failed",
            error_msg="not found",
            script_fragment="page.click('#x')",
            failed_step=1,
        )
        response = await diagnose_script(str(uuid4()), request, mock_db)

        assert response["code"] == 0
        card = response["data"]["diagnosis_card"]
        assert card["can_fix"] is True
        assert card["revised_step"] == "new code"
        assert response["data"]["revised_script"] is not None
        assert "original content" in response["data"]["revised_script"]
        assert "new code" in response["data"]["revised_script"]
        # version bumped + ai_diagnosis set on the asset (#5c: array-ized, mode+created_at added)
        assert mock_asset.version == 2
        assert len(mock_asset.ai_diagnosis) == 1
        stored = mock_asset.ai_diagnosis[0]
        assert stored["category"] == card["category"]
        assert stored["revised_step"] == card["revised_step"]
        assert stored["mode"] == "rule"
        assert "created_at" in stored
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_diagnose_cannot_fix_returns_card_no_revised_script(self, mock_db, monkeypatch):
        """can_fix=False -> diagnosis card returned, revised_script None, no commit."""
        from app.api.v1 import scripts as scripts_api
        from app.api.v1.scripts import diagnose_script
        from app.schemas.script import DiagnoseRequest

        class FakeDiag:
            async def diagnose(self, **kw):
                return {
                    "category": "page_bug",
                    "can_fix": False,
                    "reason": "断言值不符",
                    "failed_step": kw.get("failed_step"),
                    "error_type": kw.get("error_type"),
                    "error_msg": kw.get("error_msg"),
                    "screenshot_url": None,
                    "revised_step": None,
                    "suggestion": "标 xfail",
                }

        monkeypatch.setattr(scripts_api, "ScriptDiagnoseService", lambda gateway: FakeDiag())
        monkeypatch.setattr(scripts_api, "AIGateway", lambda: None)

        mock_asset = MagicMock()
        mock_asset.content = "original"
        mock_asset.version = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_asset)
        mock_db.execute.return_value = mock_result

        request = DiagnoseRequest(
            error_type="assertion_failed",
            error_msg="value mismatch",
            script_fragment="expect(page.locator('#x')).to_have_text('A')",
            failed_step=2,
        )
        response = await diagnose_script(str(uuid4()), request, mock_db)

        assert response["code"] == 0
        assert response["data"]["diagnosis_card"]["can_fix"] is False
        assert response["data"]["revised_script"] is None
        # version NOT bumped, content NOT changed, no commit
        assert mock_asset.version == 1
        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_diagnose_not_found(self, mock_db, monkeypatch):
        """Asset missing -> 404."""
        from app.api.v1 import scripts as scripts_api
        from app.api.v1.scripts import diagnose_script
        from app.schemas.script import DiagnoseRequest

        monkeypatch.setattr(scripts_api, "ScriptDiagnoseService", lambda gateway: MagicMock())
        monkeypatch.setattr(scripts_api, "AIGateway", lambda: None)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_result

        request = DiagnoseRequest(
            error_type="locate_failed",
            error_msg="not found",
            script_fragment="page.click('#x')",
        )
        with pytest.raises(HTTPException) as exc_info:
            await diagnose_script(str(uuid4()), request, mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_diagnose_invalid_uuid(self, mock_db):
        """Invalid UUID -> 400."""
        from app.api.v1.scripts import diagnose_script
        from app.schemas.script import DiagnoseRequest

        request = DiagnoseRequest(
            error_type="locate_failed",
            error_msg="not found",
            script_fragment="page.click('#x')",
        )
        with pytest.raises(HTTPException) as exc_info:
            await diagnose_script("not-a-uuid", request, mock_db)

        assert exc_info.value.status_code == 400


class TestScriptStats:
    """Test GET /api/v1/scripts/stats (模块 #5a, Task 7)"""

    def test_stats_aggregation(self, monkeypatch):
        from app.api.v1.scripts import get_script_stats

        class FakeSA:
            def __init__(self, last_status, run_count):
                self.last_status = last_status
                self.run_count = run_count

        scripts = [
            FakeSA("passed", 1),
            FakeSA("failed", 2),
            FakeSA("never_run", 0),
            FakeSA("never_run", 0),
        ]
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = scripts
        db.execute = AsyncMock(return_value=result)
        stats = asyncio_run(
            get_script_stats(
                project_id="00000000-0000-0000-0000-000000000001", db=db
            )
        )
        assert stats["code"] == 0
        assert stats["data"]["total"] == 4
        assert stats["data"]["passed"] == 1
        assert stats["data"]["failed"] == 1
        assert stats["data"]["never_run"] == 2
        assert stats["data"]["pass_rate"] == 25.0  # 1/4*100


class TestListCategoryKeyword:
    """Test list_scripts category/keyword filter (SCRIPT-02, 模块 #5a Task 7)"""

    def test_list_filters_by_category_and_keyword(self, monkeypatch):
        from app.api.v1.scripts import list_scripts

        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        asyncio_run(
            list_scripts(
                project_id="00000000-0000-0000-0000-000000000001",
                category="ui_smoke",
                keyword="登录",
                page=1,
                page_size=20,
                db=db,
            )
        )
        # 验证 execute 被调用 (stmt 构建不报错即可)
        db.execute.assert_awaited_once()


class TestBatchRunEndpoint:
    """Test POST /api/v1/scripts/batch-run (模块 #5a Task 验收)"""

    @pytest.mark.asyncio
    async def test_batch_run_validates_script_ids_existence(self, monkeypatch):
        """全部 script_ids 不存在 -> 400."""
        from app.api.v1.scripts import batch_run_scripts
        from app.schemas.script import BatchRunRequest, RunConfig

        db = MagicMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result)

        request = BatchRunRequest(
            script_ids=[str(uuid4()), str(uuid4())],
            config=RunConfig(),
        )
        with pytest.raises(HTTPException) as exc_info:
            await batch_run_scripts(request, db)
        assert exc_info.value.status_code == 400
        assert "无有效脚本" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_batch_run_invalid_uuid_rejected(self):
        """script_ids 含非法 UUID -> 400."""
        from app.api.v1.scripts import batch_run_scripts
        from app.schemas.script import BatchRunRequest, RunConfig

        db = MagicMock()
        request = BatchRunRequest(
            script_ids=["not-a-uuid"],
            config=RunConfig(),
        )
        with pytest.raises(HTTPException) as exc_info:
            await batch_run_scripts(request, db)
        assert exc_info.value.status_code == 400
        assert "Invalid UUID" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_batch_run_dispatches_when_some_exist(self):
        """至少一个 script_id 有效 -> 派发 Celery 任务."""
        from app.api.v1.scripts import batch_run_scripts
        from app.schemas.script import BatchRunRequest, RunConfig

        mock_asset = MagicMock()
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[mock_asset]))
        )
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        valid_id = str(uuid4())
        request = BatchRunRequest(
            script_ids=[valid_id],
            config=RunConfig(),
        )
        with patch("app.api.v1.scripts.run_scripts_task") as mock_task:
            mock_task.delay = MagicMock()
            response = await batch_run_scripts(request, db)
        assert response["code"] == 0
        assert "session_id" in response["data"]
        mock_task.delay.assert_called_once()
        _, kwargs = mock_task.delay.call_args
        assert kwargs["script_ids"] == [valid_id]
