"""
Test Case Service Unit Tests
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from uuid import uuid4, UUID
from datetime import datetime

from app.services.test_case_service import TestCaseService
from app.schemas.test_case import (
    CaseCreateRequest,
    CaseUpdateRequest,
    CaseFilterParams,
    BatchOperationRequest,
    StepSchema,
)


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    db.add = Mock()
    return db


@pytest.fixture
def service(mock_db):
    """Create TestCaseService instance with mocked db"""
    return TestCaseService(mock_db)


@pytest.fixture
def sample_project_id():
    """Sample project UUID"""
    return str(uuid4())


@pytest.fixture
def sample_case_id():
    """Sample case UUID"""
    return str(uuid4())


@pytest.fixture
def sample_steps():
    """Sample test steps"""
    return [
        StepSchema(step=1, action="Open login page", target="URL", data="https://example.com", expected="Page loads"),
        StepSchema(step=2, action="Enter username", target="input#username", data="testuser", expected="Username entered"),
        StepSchema(step=3, action="Click login", target="button#login", data=None, expected="Login successful"),
    ]


class TestListCases:
    """Test list_cases functionality"""

    @pytest.mark.asyncio
    async def test_list_cases_empty(self, service, mock_db, sample_project_id):
        """Test listing cases when none exist"""
        # Mock count query result (total = 0)
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        # Mock data query result (empty list)
        data_result = MagicMock()
        data_result.all.return_value = []

        # Configure execute to return different results based on call order
        mock_db.execute.side_effect = [count_result, data_result]

        filters = CaseFilterParams(project_id=sample_project_id, page=1, page_size=20)
        result = await service.list_cases(filters)

        assert result.total == 0
        assert result.page == 1
        assert result.page_size == 20
        assert len(result.items) == 0
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_list_cases_with_data(self, service, mock_db, sample_project_id):
        """Test listing cases with data"""
        # Create mock test case
        mock_case = MagicMock()
        mock_case.id = uuid4()
        mock_case.project_id = UUID(sample_project_id)
        mock_case.point_id = uuid4()
        mock_case.name = "Test login functionality"
        mock_case.priority = "P0"
        mock_case.case_type = "functional"
        mock_case.automation_status = "pending"
        mock_case.expected_result = "User can login successfully"
        mock_case.is_finalized = False
        mock_case.version = 1
        mock_case.hallucination_status = "normal"
        # W7: review fields now surfaced on list items (CaseResponse)
        mock_case.review_status = "pending"
        mock_case.feasibility_level = None
        mock_case.refinement_report = None
        mock_case.refined_at = None
        mock_case.created_by = "tester"
        mock_case.created_at = datetime.now()
        mock_case.updated_at = datetime.now()

        # Mock count query result
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        # Mock data query result
        data_result = MagicMock()
        data_result.all.return_value = [(mock_case, "Login Page")]

        mock_db.execute.side_effect = [count_result, data_result]

        filters = CaseFilterParams(project_id=sample_project_id, page=1, page_size=20)
        result = await service.list_cases(filters)

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "Test login functionality"
        assert result.items[0].priority == "P0"
        assert result.items[0].point_name == "Login Page"

    @pytest.mark.asyncio
    async def test_list_cases_with_filters(self, service, mock_db, sample_project_id):
        """Test listing cases with priority and keyword filters"""
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        data_result = MagicMock()
        data_result.all.return_value = []
        mock_db.execute.side_effect = [count_result, data_result]

        filters = CaseFilterParams(
            project_id=sample_project_id,
            priority="P0",
            keyword="login",
            page=1,
            page_size=20
        )
        result = await service.list_cases(filters)

        assert result.total == 0
        assert mock_db.execute.call_count == 2


class TestGetCaseDetail:
    """Test get_case_detail functionality"""

    @pytest.mark.asyncio
    async def test_get_case_detail_found(self, service, mock_db, sample_case_id, sample_project_id):
        """Test getting case detail when case exists"""
        mock_case = MagicMock()
        mock_case.id = UUID(sample_case_id)
        mock_case.project_id = UUID(sample_project_id)
        mock_case.point_id = uuid4()
        mock_case.name = "Test login"
        mock_case.priority = "P1"
        mock_case.case_type = "functional"
        mock_case.automation_status = "pending"
        mock_case.precondition = "User is on homepage"
        mock_case.steps = [{"step": 1, "action": "Click login", "expected": "Login page opens"}]
        mock_case.expected_result = "User logged in"
        mock_case.is_finalized = False
        mock_case.version = 1
        mock_case.hallucination_status = "normal"
        mock_case.created_by = "tester"
        mock_case.created_at = datetime.now()
        mock_case.updated_at = datetime.now()
        mock_case.is_deleted = False
        mock_case.review_status = "pending"
        mock_case.review_comment = None
        mock_case.feasibility_level = None
        mock_case.cannot_automate_reason = None
        mock_case.refinement_report = None
        mock_case.refined_at = None

        result_mock = MagicMock()
        # get_case_detail 用 .first() 取 (case, project_name, test_point_name) 行
        result_mock.first.return_value = (mock_case, "Test Project", "Test Point")
        mock_db.execute.return_value = result_mock

        result = await service.get_case_detail(sample_case_id)

        assert result is not None
        assert result.name == "Test login"
        assert result.priority == "P1"
        assert len(result.steps) == 1
        assert result.project_name == "Test Project"
        assert result.test_point_name == "Test Point"

    @pytest.mark.asyncio
    async def test_get_case_detail_not_found(self, service, mock_db, sample_case_id):
        """Test getting case detail when case does not exist"""
        result_mock = MagicMock()
        # get_case_detail 用 .first()；无行返回 None
        result_mock.first.return_value = None
        mock_db.execute.return_value = result_mock

        result = await service.get_case_detail(sample_case_id)

        assert result is None


class TestCreateCase:
    """Test create_case functionality"""

    @pytest.mark.asyncio
    async def test_create_case_success(self, service, mock_db, sample_project_id, sample_steps):
        """Test successful case creation"""
        request = CaseCreateRequest(
            project_id=sample_project_id,
            point_id=None,
            name="Test user login",
            priority="P0",
            case_type="functional",
            automation_status="pending",
            precondition="User has valid credentials",
            steps=sample_steps,
            expected_result="User can login successfully",
            created_by="tester1"
        )

        # Mock the refresh to populate the new_case with id and timestamps
        async def mock_refresh(obj):
            obj.id = uuid4()
            obj.created_at = datetime.now()
            obj.updated_at = datetime.now()
            obj.is_deleted = False

        mock_db.refresh.side_effect = mock_refresh

        result = await service.create_case(request)

        assert result.name == "Test user login"
        assert result.priority == "P0"
        assert len(result.steps) == 3
        assert result.version == 1
        assert result.is_finalized is False
        assert mock_db.add.called
        assert mock_db.commit.called


class TestUpdateCase:
    """Test update_case functionality"""

    @pytest.mark.asyncio
    async def test_update_case_success(self, service, mock_db, sample_case_id, sample_project_id):
        """Test successful case update"""
        mock_case = MagicMock()
        mock_case.id = UUID(sample_case_id)
        mock_case.project_id = UUID(sample_project_id)
        mock_case.point_id = None
        mock_case.name = "Old name"
        mock_case.priority = "P1"
        mock_case.case_type = "functional"
        mock_case.automation_status = "pending"
        mock_case.precondition = "Old precondition"
        mock_case.steps = []
        mock_case.expected_result = "Old result"
        mock_case.is_finalized = False
        mock_case.version = 1
        mock_case.hallucination_status = "normal"
        mock_case.created_by = "tester"
        mock_case.created_at = datetime.now()
        mock_case.updated_at = datetime.now()
        mock_case.is_deleted = False
        mock_case.review_status = "pending"
        mock_case.review_comment = None
        mock_case.feasibility_level = None
        mock_case.cannot_automate_reason = None
        mock_case.refinement_report = None
        mock_case.refined_at = None

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_case
        mock_db.execute.return_value = result_mock

        request = CaseUpdateRequest(
            name="Updated name",
            priority="P0"
        )

        result = await service.update_case(sample_case_id, request)

        assert result is not None
        assert mock_case.name == "Updated name"
        assert mock_case.priority == "P0"
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_update_case_not_found(self, service, mock_db, sample_case_id):
        """Test updating non-existent case"""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result_mock

        request = CaseUpdateRequest(name="New name")
        result = await service.update_case(sample_case_id, request)

        assert result is None

    @pytest.mark.asyncio
    async def test_update_finalized_case_fails(self, service, mock_db, sample_case_id, sample_project_id):
        """Test that updating finalized case raises ValueError"""
        mock_case = MagicMock()
        mock_case.is_finalized = True
        mock_case.is_deleted = False

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_case
        mock_db.execute.return_value = result_mock

        request = CaseUpdateRequest(name="New name")

        with pytest.raises(ValueError, match="Cannot update finalized test case"):
            await service.update_case(sample_case_id, request)


class TestDeleteCase:
    """Test delete_case functionality"""

    @pytest.mark.asyncio
    async def test_delete_case_success(self, service, mock_db, sample_case_id):
        """Test successful soft delete"""
        mock_case = MagicMock()
        mock_case.is_deleted = False

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_case
        mock_db.execute.return_value = result_mock

        result = await service.delete_case(sample_case_id)

        assert result is True
        assert mock_case.is_deleted is True
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_delete_case_not_found(self, service, mock_db, sample_case_id):
        """Test deleting non-existent case"""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result_mock

        result = await service.delete_case(sample_case_id)

        assert result is False


class TestBatchOperation:
    """Test batch_operation functionality"""

    @pytest.mark.asyncio
    async def test_batch_delete_success(self, service, mock_db):
        """Test batch delete operation"""
        case_ids = [str(uuid4()), str(uuid4())]
        mock_cases = [MagicMock(id=UUID(cid), is_deleted=False) for cid in case_ids]

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = mock_cases
        mock_db.execute.return_value = result_mock

        request = BatchOperationRequest(case_ids=case_ids, action="delete")
        result = await service.batch_operation(request)

        assert result["success_count"] == 2
        assert result["failure_count"] == 0
        assert all(case.is_deleted is True for case in mock_cases)
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_batch_finalize_success(self, service, mock_db):
        """Test batch finalize operation"""
        case_ids = [str(uuid4()), str(uuid4())]
        mock_cases = [MagicMock(id=UUID(cid), is_finalized=False) for cid in case_ids]

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = mock_cases
        mock_db.execute.return_value = result_mock

        request = BatchOperationRequest(case_ids=case_ids, action="finalize")
        result = await service.batch_operation(request)

        assert result["success_count"] == 2
        assert all(case.is_finalized is True for case in mock_cases)

    @pytest.mark.asyncio
    async def test_batch_operation_no_cases_found(self, service, mock_db):
        """Test batch operation when no cases found"""
        case_ids = [str(uuid4())]

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = result_mock

        request = BatchOperationRequest(case_ids=case_ids, action="delete")
        result = await service.batch_operation(request)

        assert result["success_count"] == 0
        assert result["failure_count"] == 1
        assert "No valid cases found" in result["errors"]


class TestGetStats:
    """Test get_stats functionality"""

    @pytest.mark.asyncio
    async def test_get_stats_empty_project(self, service, mock_db, sample_project_id):
        """Test statistics for empty project"""
        # Mock all query results to return 0
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.all.return_value = []

        mock_db.execute.return_value = mock_result

        result = await service.get_stats(sample_project_id)

        assert result.total_cases == 0
        assert result.finalized_count == 0
        assert result.hallucination_count == 0
        assert len(result.by_priority) == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_data(self, service, mock_db, sample_project_id):
        """Test statistics with data"""
        # Mock total count
        total_result = MagicMock()
        total_result.scalar.return_value = 10

        # Mock priority counts
        priority_result = MagicMock()
        priority_result.all.return_value = [("P0", 2), ("P1", 5), ("P2", 3)]

        # Mock case type counts
        case_type_result = MagicMock()
        case_type_result.all.return_value = [("functional", 7), ("interface_case", 3)]

        # Mock automation status counts
        automation_result = MagicMock()
        automation_result.all.return_value = [("pending", 6), ("automated", 4)]

        # Mock finalized count
        finalized_result = MagicMock()
        finalized_result.scalar.return_value = 3

        # Mock hallucination count
        hallucination_result = MagicMock()
        hallucination_result.scalar.return_value = 1

        mock_db.execute.side_effect = [
            total_result,
            priority_result,
            case_type_result,
            automation_result,
            finalized_result,
            hallucination_result
        ]

        result = await service.get_stats(sample_project_id)

        assert result.total_cases == 10
        assert result.by_priority == {"P0": 2, "P1": 5, "P2": 3}
        assert result.by_case_type == {"functional": 7, "interface_case": 3}
        assert result.by_automation_status == {"pending": 6, "automated": 4}
        assert result.finalized_count == 3
        assert result.hallucination_count == 1
