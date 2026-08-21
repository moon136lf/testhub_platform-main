"""W4 import/export tests."""
import json
import io
import pytest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from app.services.import_export_service import ImportExportService


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = Mock()
    return db


def _sample_cases():
    case = Mock()
    case.id = uuid4()
    case.project_id = uuid4()
    case.point_id = None
    case.name = "登录-正常"
    case.priority = "P1"
    case.case_type = "functional"
    case.automation_status = "pending"
    case.precondition = "已打开登录页"
    case.steps = [{"step":1,"action":"点击登录","target":"登录按钮","data":"","expected":"跳转首页"}]
    case.expected_result = "进入首页"
    case.is_finalized = False
    case.version = 1
    case.hallucination_status = "normal"
    case.created_by = "u"
    case.created_at = case.updated_at = None
    case.is_deleted = False
    return [case]


class TestExportJson:
    @pytest.mark.asyncio
    async def test_export_json_produces_valid_array(self, mock_db):
        mock_db.execute.return_value = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=_sample_cases()))))
        svc = ImportExportService(mock_db)
        result = await svc.export_cases_async(str(uuid4()), "json")
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["name"] == "登录-正常"
        assert data[0]["steps"][0]["step"] == 1


class TestImportCsv:
    @pytest.mark.asyncio
    async def test_name_conflict_skipped(self, mock_db):
        # existing case with same name -> IntegrityError on commit
        from sqlalchemy.exc import IntegrityError
        csv_content = "name,priority,case_type,precondition,steps,expected_result\n登录-正常,P1,functional,,[],进入首页\n新建用例,P1,functional,,[],结果\n"
        # first commit (conflict) raises, second succeeds
        commits = [IntegrityError("stmt", {}, Exception("dup")), None]
        async def fake_commit():
            if commits:
                err = commits.pop(0)
                if err:
                    raise err
        mock_db.commit = fake_commit
        svc = ImportExportService(mock_db)
        result = await svc.import_cases(str(uuid4()), csv_content.encode("utf-8"), "csv")
        assert result["failed"] == 1
        assert result["imported"] == 1
