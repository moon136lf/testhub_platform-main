"""
AI Case Generation API Tests
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
    """Mock database session"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def sample_project_id():
    """Sample project UUID"""
    return str(uuid4())


@pytest.fixture
def sample_session_id():
    """Sample session UUID"""
    return str(uuid4())


class TestUploadDocumentEndpoint:
    """Test POST /api/v1/ai-case-generation/upload-document"""

    @pytest.mark.asyncio
    async def test_upload_document_with_file(self, mock_db, sample_project_id):
        """Test uploading a document file"""
        from app.api.v1.ai_case_generation import upload_document
        from app.api.v1.ai_case_generation import UploadDocumentRequest

        # Mock project exists
        mock_project = MagicMock()
        mock_project.id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_project)
        mock_db.execute.return_value = mock_result

        request = UploadDocumentRequest(
            project_id=sample_project_id,
            file_bytes=b"test content",
            file_type="docx"
        )

        # Mock Celery task - patch the module attribute referenced by the API
        with patch('app.api.v1.ai_case_generation.parse_document_task') as mock_task:
            mock_task.delay = MagicMock()
            mock_task.delay.return_value.id = "task-123"

            response = await upload_document(request, mock_db)

            # upload_document 返回 UploadDocumentResponse 模型，转 dict 断言
            assert response.code == 0
            assert "session_id" in response.data
            assert "task_id" in response.data
            assert "sse_url" in response.data

    @pytest.mark.asyncio
    async def test_upload_document_file_too_large(self, mock_db, sample_project_id):
        """Test upload with file exceeding size limit"""
        from app.api.v1.ai_case_generation import UploadDocumentRequest
        from pydantic import ValidationError

        # Create file larger than 10MB
        large_file = b"x" * (11 * 1024 * 1024)

        with pytest.raises(ValidationError) as exc_info:
            UploadDocumentRequest(
                project_id=sample_project_id,
                file_bytes=large_file,
                file_type="pdf"
            )

        assert "File size exceeds maximum" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_document_invalid_file_type(self, mock_db, sample_project_id):
        """Test upload with invalid file type"""
        from app.api.v1.ai_case_generation import UploadDocumentRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            UploadDocumentRequest(
                project_id=sample_project_id,
                file_bytes=b"test",
                file_type="exe"  # Invalid type
            )

        assert "Invalid file type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_document_invalid_project(self, mock_db):
        """Test upload with invalid project ID"""
        from app.api.v1.ai_case_generation import upload_document
        from app.api.v1.ai_case_generation import UploadDocumentRequest

        # Mock project not found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_result

        request = UploadDocumentRequest(
            project_id=str(uuid4()),
            file_bytes=b"test",
            file_type="txt"
        )

        with pytest.raises(HTTPException) as exc_info:
            await upload_document(request, mock_db)

        assert exc_info.value.status_code == 404
        assert "Project not found" in str(exc_info.value.detail)


class TestSearchKnowledgeEndpoint:
    """Test POST /api/v1/ai-case-generation/search-knowledge"""

    @pytest.mark.asyncio
    async def test_search_knowledge_success(self, mock_db, sample_project_id):
        """Test triggering knowledge search"""
        from app.api.v1.ai_case_generation import search_knowledge
        from app.api.v1.ai_case_generation import SearchKnowledgeRequest

        request = SearchKnowledgeRequest(
            session_id=str(uuid4()),
            project_id=sample_project_id,
            doc_content="Test PRD content"
        )

        # Mock Celery task - patch the module attribute referenced by the API
        with patch('app.api.v1.ai_case_generation.retrieve_knowledge_task') as mock_task:
            mock_task.delay = MagicMock()
            mock_task.delay.return_value.id = "task-456"

            response = await search_knowledge(request, mock_db)

            assert response["code"] == 0
            assert "task_id" in response["data"]
            assert response["data"]["session_id"] == request.session_id


class TestGetKnowledgeResultsEndpoint:
    """Test GET /api/v1/ai-case-generation/knowledge-results/{session_id}"""

    @pytest.mark.asyncio
    async def test_get_knowledge_results_from_cache(self, mock_db, sample_session_id):
        """Test retrieving knowledge results from cache"""
        from app.api.v1.ai_case_generation import get_knowledge_results

        mock_results = [
            {"document_id": str(uuid4()), "chunk_text": "Test chunk 1", "similarity": 0.95},
            {"document_id": str(uuid4()), "chunk_text": "Test chunk 2", "similarity": 0.87}
        ]

        # Mock Redis cache
        with patch('app.core.sse.SSEStream.get_cached_result') as mock_cache:
            mock_cache.return_value = {"knowledge_results": mock_results}

            response = await get_knowledge_results(sample_session_id, mock_db)

            assert response["code"] == 0
            assert len(response["data"]["knowledge_results"]) == 2


class TestIdentifyPointsEndpoint:
    """Test POST /api/v1/ai-case-generation/identify-points"""

    @pytest.mark.asyncio
    async def test_identify_points_success(self, mock_db, sample_project_id):
        """Test AI identify test points"""
        from app.api.v1.ai_case_generation import identify_points
        from app.api.v1.ai_case_generation import IdentifyPointsRequest

        rule_id = str(uuid4())

        # Mock project exists
        mock_project = MagicMock()
        mock_project.id = uuid4()

        # Mock rule exists
        mock_rule = MagicMock()
        mock_rule.id = uuid4()

        # Setup multiple execute calls
        mock_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_project)),  # project check
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_rule]))))  # rules check
        ]
        mock_db.execute.side_effect = mock_results

        # Mock Celery task - patch the module attribute referenced by the API
        with patch('app.api.v1.ai_case_generation.identify_test_points_task') as mock_task:
            mock_task.delay = MagicMock()
            mock_task.delay.return_value.id = "task-789"

            request = IdentifyPointsRequest(
                session_id=str(uuid4()),
                project_id=sample_project_id,
                document_content="PRD content here",
                rule_ids=[rule_id],
                knowledge_ids=[str(uuid4())]
            )

            response = await identify_points(request, mock_db)

            assert response["code"] == 0
            assert "task_id" in response["data"]

    @pytest.mark.asyncio
    async def test_identify_points_invalid_rule_id(self, mock_db, sample_project_id):
        """Test identify points with non-existent rule"""
        from app.api.v1.ai_case_generation import identify_points
        from app.api.v1.ai_case_generation import IdentifyPointsRequest

        # Mock project exists
        mock_project = MagicMock()
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none = MagicMock(return_value=mock_project)

        # Mock rules not found
        mock_result_rules = MagicMock()
        mock_result_rules.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        mock_db.execute.side_effect = [mock_result_project, mock_result_rules]

        request = IdentifyPointsRequest(
            session_id=str(uuid4()),
            project_id=sample_project_id,
            document_content="PRD content",
            rule_ids=[str(uuid4())],
            knowledge_ids=[]
        )

        with pytest.raises(HTTPException) as exc_info:
            await identify_points(request, mock_db)

        assert exc_info.value.status_code == 404
        assert "rules not found" in str(exc_info.value.detail)



class TestGetTestPointsEndpoint:
    """Test GET /api/v1/ai-case-generation/test-points"""

    @pytest.mark.asyncio
    async def test_get_test_points_success(self, mock_db, sample_project_id):
        """Test getting test points list"""
        from app.api.v1.ai_case_generation import get_test_points

        # Mock test points
        mock_point1 = MagicMock()
        mock_point1.to_dict = MagicMock(return_value={
            "id": str(uuid4()),
            "name": "Test point 1",
            "status": "pending"
        })
        mock_point2 = MagicMock()
        mock_point2.to_dict = MagicMock(return_value={
            "id": str(uuid4()),
            "name": "Test point 2",
            "status": "approved"
        })

        mock_result = MagicMock()
        mock_result.scalars = MagicMock()
        mock_result.scalars.return_value.all = MagicMock(return_value=[mock_point1, mock_point2])
        mock_db.execute.return_value = mock_result

        # 签名: get_test_points(project_id, status, skip, limit, db)
        response = await get_test_points(sample_project_id, None, 0, 100, mock_db)

        assert response["code"] == 0
        assert len(response["data"]) == 2


class TestUpdateTestPointEndpoint:
    """Test PUT /api/v1/ai-case-generation/test-points/{point_id}"""

    @pytest.mark.asyncio
    async def test_update_test_point_success(self, mock_db):
        """Test updating test point"""
        from app.api.v1.ai_case_generation import update_test_point
        from app.api.v1.ai_case_generation import TestPointUpdate

        point_id = str(uuid4())

        # Mock existing point
        mock_point = MagicMock()
        mock_point.id = uuid4()
        mock_point.name = "Original name"
        mock_point.to_dict = MagicMock(return_value={"id": point_id, "name": "Updated name"})

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_point)
        mock_db.execute.return_value = mock_result

        update_data = TestPointUpdate(name="Updated name")

        response = await update_test_point(point_id, update_data, mock_db)

        assert response["code"] == 0
        assert response["data"]["name"] == "Updated name"


class TestCreateTestPointEndpoint:
    """Test POST /api/v1/ai-case-generation/test-points"""

    @pytest.mark.asyncio
    async def test_create_test_point_success(self, mock_db, sample_project_id):
        """Test manually creating test point"""
        from app.api.v1.ai_case_generation import create_test_point
        from app.api.v1.ai_case_generation import TestPointCreate

        request = TestPointCreate(
            project_id=sample_project_id,
            page_name="Login Page",
            name="Test login validation",
            type_label="Functional",
            description="Test user login with invalid credentials"
        )

        response = await create_test_point(request, mock_db)

        assert response["code"] == 0
        assert "id" in response["data"]


class TestGenerateCasesEndpoint:
    """Test POST /api/v1/ai-case-generation/generate-cases"""

    @pytest.mark.asyncio
    async def test_generate_cases_success(self, mock_db, sample_project_id):
        """Test batch generate test cases"""
        from app.api.v1.ai_case_generation import generate_cases
        from app.api.v1.ai_case_generation import GenerateCasesRequest

        point_ids = [str(uuid4()), str(uuid4())]

        # Mock project exists
        mock_project = MagicMock()
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none = MagicMock(return_value=mock_project)

        # Mock test points exist
        mock_points = [MagicMock(), MagicMock()]
        mock_result_points = MagicMock()
        mock_result_points.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=mock_points)))

        # 会话查询（session 行存在分支）→ 加一个返回 None 的结果
        mock_result_session = MagicMock()
        mock_result_session.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.side_effect = [mock_result_project, mock_result_points, mock_result_session]

        # Mock Celery task - patch the module attribute referenced by the API
        with patch('app.api.v1.ai_case_generation.generate_test_cases_task') as mock_task:
            mock_task.delay = MagicMock()
            mock_task.delay.return_value.id = "task-abc"

            request = GenerateCasesRequest(
                session_id=str(uuid4()),
                project_id=sample_project_id,
                point_ids=point_ids,
                hallucination_strategy="moderate"
            )

            response = await generate_cases(request, mock_db)

            assert response["code"] == 0
            assert "task_id" in response["data"]

    @pytest.mark.asyncio
    async def test_generate_cases_point_not_found(self, mock_db, sample_project_id):
        """Test generate cases with non-existent test point"""
        from app.api.v1.ai_case_generation import generate_cases
        from app.api.v1.ai_case_generation import GenerateCasesRequest

        # Mock project exists
        mock_project = MagicMock()
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none = MagicMock(return_value=mock_project)

        # Mock only one point found instead of two
        mock_result_points = MagicMock()
        mock_result_points.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[MagicMock()])))

        mock_db.execute.side_effect = [mock_result_project, mock_result_points]

        request = GenerateCasesRequest(
            session_id=str(uuid4()),
            project_id=sample_project_id,
            point_ids=[str(uuid4()), str(uuid4())],
            hallucination_strategy="moderate"
        )

        with pytest.raises(HTTPException) as exc_info:
            await generate_cases(request, mock_db)

        assert exc_info.value.status_code == 404
        assert "test points not found" in str(exc_info.value.detail).lower()


class TestGetTestCasesEndpoint:
    """Test GET /api/v1/ai-case-generation/test-cases"""

    @pytest.mark.asyncio
    async def test_get_test_cases_success(self, mock_db, sample_project_id):
        """Test getting generated test cases"""
        from app.api.v1.ai_case_generation import get_test_cases

        # Mock test cases
        mock_case = MagicMock()
        mock_case.to_dict = MagicMock(return_value={
            "id": str(uuid4()),
            "name": "Test case 1",
            "priority": "P1"
        })

        mock_result = MagicMock()
        mock_result.scalars = MagicMock()
        mock_result.scalars.return_value.all = MagicMock(return_value=[mock_case])
        mock_db.execute.return_value = mock_result

        # 签名: get_test_cases(project_id, point_id, hallucination_status, skip, limit, db)
        response = await get_test_cases(sample_project_id, None, None, 0, 100, mock_db)

        assert response["code"] == 0
        assert len(response["data"]) == 1


class TestGetRulesEndpoint:
    """Test GET /api/v1/ai-case-generation/rules"""

    @pytest.mark.asyncio
    async def test_get_rules_success(self, mock_db):
        """Test getting all rules"""
        from app.api.v1.ai_case_generation import get_rules

        # Mock rules
        mock_rule = MagicMock()
        mock_rule.id = uuid4()
        mock_rule.name = "Automation-first"
        mock_rule.description = "Prioritize automatable test points"
        mock_rule.is_builtin = True
        mock_rule.status = "active"
        mock_rule.prompt_template = None
        mock_rule.created_by = "system"
        mock_rule.created_at = MagicMock()
        mock_rule.created_at.isoformat = MagicMock(return_value="2026-08-21T00:00:00")

        mock_result = MagicMock()
        mock_result.scalars = MagicMock()
        mock_result.scalars.return_value.all = MagicMock(return_value=[mock_rule])
        mock_db.execute.return_value = mock_result

        # 签名: get_rules(skip, limit, db)
        response = await get_rules(0, 100, mock_db)

        assert response["code"] == 0
        assert len(response["data"]) == 1


class TestCreateRuleEndpoint:
    """Test POST /api/v1/ai-case-generation/rules"""

    @pytest.mark.asyncio
    async def test_create_rule_success(self, mock_db):
        """Test creating custom rule"""
        from app.api.v1.ai_case_generation import create_rule
        from app.api.v1.ai_case_generation import RuleCreate

        request = RuleCreate(
            name="Custom rule",
            description="My custom test rule",
            prompt_template="Focus on: {criteria}"
        )

        response = await create_rule(request, mock_db)

        assert response["code"] == 0
        assert response["data"]["name"] == "Custom rule"
