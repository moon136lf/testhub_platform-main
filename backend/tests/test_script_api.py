"""
Script conversion API tests (模块 #4, Task 13).

Mirrors the repo convention from test_api_ai_case_generation.py: call the
endpoint function directly with an AsyncMock db session and patch the Celery
task — no ASGI client, no real DB, no dependency_overrides.
"""

import sys
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from fastapi import HTTPException

# Add backend directory to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))


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

        response = await list_scripts(None, None, 1, 20, mock_db)

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
