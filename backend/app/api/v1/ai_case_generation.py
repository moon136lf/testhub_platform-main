"""
AI Case Generation API endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime
import uuid
import tempfile
import os

from app.core.database import get_db
from app.tasks.ai_case_tasks import (
    parse_document_task,
    retrieve_knowledge_task,
    identify_test_points_task,
    generate_test_cases_task
)
from app.models.project import Project
from app.models.test_case import TestPoint, TestCase
from app.models.test_rule import TestRule
from app.models.generation import GenerationSession
from app.models.execution import AICallLog
from app.core.sse import SSEStream
from app.schemas.generation import GenerationRules

router = APIRouter()

# Constants
ALLOWED_FILE_TYPES = {"docx", "pdf", "txt", "md"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_USER = "system"


# Request/Response Schemas

class UploadDocumentRequest(BaseModel):
    """Step 2: Upload PRD document request"""
    project_id: str = Field(..., description="Project ID")
    file_bytes: Optional[bytes] = Field(None, description="File content in bytes")
    file_type: Optional[str] = Field(None, description="File type: docx, pdf, txt, md")
    text_content: Optional[str] = Field(None, description="Direct text input")

    @field_validator('file_bytes')
    @classmethod
    def validate_file_size(cls, v):
        if v is not None and len(v) > MAX_FILE_SIZE_BYTES:
            raise ValueError(f'File size exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES / (1024 * 1024):.0f}MB')
        return v

    @field_validator('file_type')
    @classmethod
    def validate_file_type(cls, v):
        if v is not None and v not in ALLOWED_FILE_TYPES:
            raise ValueError(f'Invalid file type. Allowed types: {", ".join(ALLOWED_FILE_TYPES)}')
        return v


class UploadDocumentResponse(BaseModel):
    """Upload document response"""
    code: int
    message: str = "success"
    data: dict


class SearchKnowledgeRequest(BaseModel):
    """Step 4: Trigger knowledge base search request"""
    session_id: str = Field(..., description="Session ID from upload step")
    project_id: str = Field(..., description="Project ID")
    doc_content: str = Field(..., description="Document content for search")


class IdentifyPointsRequest(BaseModel):
    """Step 5: AI identify test points request"""
    session_id: str = Field(..., description="Session ID")
    project_id: str = Field(..., description="Project ID")
    document_content: str = Field(..., description="PRD text content")
    rule_ids: List[str] = Field(default=[], description="Selected test rule IDs")
    knowledge_ids: List[str] = Field(default=[], description="Selected knowledge document IDs")
    rules: Optional[GenerationRules] = Field(
        default=None, description="4 generation rule switches (automation_thinking forced on)"
    )


class TestPointUpdate(BaseModel):
    """Step 6: Edit test point request"""
    name: Optional[str] = Field(None, max_length=100)
    page_name: Optional[str] = Field(None, max_length=50)
    type_label: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = Field(None, max_length=500)
    status: Optional[str] = Field(None, pattern="^(pending|selected|generated)$")


class TestPointCreate(BaseModel):
    """Step 6: Manually add test point request"""
    project_id: str = Field(..., description="Project ID")
    page_name: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    type_label: str = Field(..., max_length=20)
    description: Optional[str] = Field(None, max_length=500)


class GenerateCasesRequest(BaseModel):
    """Step 7: Batch generate test cases request"""
    session_id: str = Field(..., description="Session ID")
    project_id: str = Field(..., description="Project ID")
    point_ids: List[str] = Field(..., description="Test point IDs to generate cases for")
    hallucination_strategy: str = Field(
        default="moderate",
        pattern="^(strict|moderate|permissive)$",
        description="Hallucination detection strategy"
    )


class RuleCreate(BaseModel):
    """Create custom rule request"""
    name: str = Field(..., max_length=50)
    description: str = Field(..., description="Rule description")
    prompt_template: Optional[str] = Field(None, description="Custom prompt template")


class RuleUpdate(BaseModel):
    """Update custom rule request (all fields optional)"""
    name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, description="Rule description")
    prompt_template: Optional[str] = Field(None, description="Custom prompt template")


# API Endpoints

@router.post("/upload-document", response_model=UploadDocumentResponse)
async def upload_document(
    request: UploadDocumentRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 2: Upload PRD document

    Accepts either a file upload (file_bytes + file_type) or direct text input (text_content).
    Returns session_id and task_id for tracking progress via SSE.
    """
    try:
        # Validate project exists
        project_uuid = uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(
        select(Project).where(Project.id == project_uuid)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate input
    if not request.file_bytes and not request.text_content:
        raise HTTPException(
            status_code=400,
            detail="Either file_bytes or text_content must be provided"
        )

    # Generate session_id
    session_id = str(uuid.uuid4())

    # Save file to temporary location if file_bytes provided
    temp_file_path = None
    if request.file_bytes:
        try:
            # Create temporary file with appropriate extension
            suffix = f".{request.file_type}" if request.file_type else ".tmp"
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=suffix) as tmp:
                tmp.write(request.file_bytes)
                temp_file_path = tmp.name
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")

    # Submit Celery task with file path instead of bytes
    task = parse_document_task.delay(
        session_id=session_id,
        file_bytes=request.file_bytes,
        file_type=request.file_type,
        text_content=request.text_content
    )

    return UploadDocumentResponse(
        code=0,
        data={
            "session_id": session_id,
            "task_id": task.id,
            "sse_url": f"/api/sse/stream/{session_id}"
        }
    )


@router.post("/search-knowledge")
async def search_knowledge(
    request: SearchKnowledgeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 4: Trigger knowledge base search

    Searches for similar historical test cases and documents based on PRD content.
    Returns task_id for tracking via SSE.
    """
    try:
        uuid.UUID(request.session_id)
        uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    if not request.doc_content or len(request.doc_content.strip()) == 0:
        raise HTTPException(status_code=400, detail="doc_content cannot be empty")

    # Submit Celery task
    task = retrieve_knowledge_task.delay(
        session_id=request.session_id,
        project_id=request.project_id,
        doc_content=request.doc_content
    )

    return {
        "code": 0,
        "message": "Knowledge search started",
        "data": {
            "session_id": request.session_id,
            "task_id": task.id,
            "sse_url": f"/api/sse/stream/{request.session_id}"
        }
    }


@router.get("/knowledge-results/{session_id}")
async def get_knowledge_results(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 4: Get knowledge search results

    Retrieves the cached results from the knowledge search task.
    """
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    # Retrieve from SSE cache
    sse = SSEStream(session_id)
    cached_result = await sse.get_cached_result()

    if not cached_result:
        raise HTTPException(
            status_code=404,
            detail="Knowledge results not found. Task may still be running."
        )

    knowledge_results = cached_result.get("knowledge_results", [])

    return {
        "code": 0,
        "data": {
            "knowledge_results": knowledge_results
        }
    }


@router.post("/identify-points")
async def identify_points(
    request: IdentifyPointsRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 5: AI identify test points

    Uses AI to analyze PRD and identify test points based on selected rules and knowledge.
    Returns task_id for tracking via SSE.
    """
    try:
        uuid.UUID(request.session_id)
        project_uuid = uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    if not request.document_content or len(request.document_content.strip()) == 0:
        raise HTTPException(status_code=400, detail="document_content cannot be empty")

    # Validate project exists
    result = await db.execute(
        select(Project).where(Project.id == project_uuid)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate rule IDs exist
    if request.rule_ids:
        try:
            rule_uuids = [uuid.UUID(rid) for rid in request.rule_ids]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid rule ID format")

        result = await db.execute(
            select(TestRule).where(TestRule.id.in_(rule_uuids))
        )
        found_rules = result.scalars().all()
        if len(found_rules) != len(rule_uuids):
            raise HTTPException(status_code=404, detail="One or more rules not found")

    # Validate knowledge IDs (assuming they should exist in some knowledge table)
    # Note: Skipping detailed validation as knowledge table structure is not defined
    if request.knowledge_ids:
        try:
            [uuid.UUID(kid) for kid in request.knowledge_ids]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid knowledge ID format")

    # 落会话记录（generation_session 表此前 0 行——生成历史无数据可查的根因之一）
    # session_id 由前端生成（uuid），直接以其为主键，供 /sessions/{id} 详情查询
    db.add(GenerationSession(
        id=uuid.UUID(request.session_id),
        project_id=project_uuid,
        document_content=request.document_content,
        selected_rules=request.rules.model_dump() if request.rules else None,
        selected_knowledge=request.knowledge_ids or None,
        current_step=5,
        status="in_progress"
    ))
    await db.commit()

    # Submit Celery task
    task = identify_test_points_task.delay(
        session_id=request.session_id,
        project_id=request.project_id,
        doc_content=request.document_content,
        rule_ids=request.rule_ids,
        knowledge_ids=request.knowledge_ids,
        rules=request.rules.model_dump() if request.rules else None
    )

    return {
        "code": 0,
        "message": "Test point identification started",
        "data": {
            "session_id": request.session_id,
            "task_id": task.id,
            "sse_url": f"/api/sse/stream/{request.session_id}"
        }
    }


@router.get("/test-points")
async def get_test_points(
    project_id: str = Query(..., description="Project ID"),
    status: Optional[str] = Query(None, description="Filter by status: pending, selected, generated"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 6: Get test points list

    Retrieves all test points for a project, with optional status filter and pagination.
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    query = select(TestPoint).where(
        TestPoint.project_id == project_uuid
    )

    if status:
        query = query.where(TestPoint.status == status)

    query = query.order_by(TestPoint.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    test_points = result.scalars().all()

    return {
        "code": 0,
        "data": [point.to_dict() for point in test_points]
    }


@router.put("/test-points/{point_id}")
async def update_test_point(
    point_id: str,
    update_data: TestPointUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 6: Edit test point

    Updates an existing test point with new values.
    """
    try:
        point_uuid = uuid.UUID(point_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid point ID format")

    result = await db.execute(
        select(TestPoint).where(TestPoint.id == point_uuid)
    )
    point = result.scalar_one_or_none()

    if not point:
        raise HTTPException(status_code=404, detail="Test point not found")

    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(point, field, value)

    await db.commit()
    await db.refresh(point)

    return {
        "code": 0,
        "message": "Test point updated successfully",
        "data": point.to_dict()
    }


@router.post("/test-points")
async def create_test_point(
    request: TestPointCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 6: Manually add test point

    Creates a new test point manually without AI assistance.
    """
    try:
        project_uuid = uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    # Create new test point
    point = TestPoint(
        project_id=project_uuid,
        page_name=request.page_name,
        name=request.name,
        type_label=request.type_label,
        description=request.description,
        status="pending"
    )

    db.add(point)
    await db.commit()
    await db.refresh(point)

    return {
        "code": 0,
        "message": "Test point created successfully",
        "data": point.to_dict()
    }


@router.post("/generate-cases")
async def generate_cases(
    request: GenerateCasesRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 7: Batch generate test cases

    Generates test cases for selected test points using AI.
    Returns task_id for tracking via SSE.
    """
    try:
        uuid.UUID(request.session_id)
        project_uuid = uuid.UUID(request.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    if not request.point_ids or len(request.point_ids) == 0:
        raise HTTPException(status_code=400, detail="point_ids cannot be empty")

    # Validate project exists
    result = await db.execute(
        select(Project).where(Project.id == project_uuid)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate all point IDs in one go
    try:
        point_uuids = [uuid.UUID(pid) for pid in request.point_ids]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid point ID format: {str(e)}")

    # Verify all test points exist
    result = await db.execute(
        select(TestPoint).where(TestPoint.id.in_(point_uuids))
    )
    found_points = result.scalars().all()
    if len(found_points) != len(point_uuids):
        raise HTTPException(status_code=404, detail="One or more test points not found")

    # Submit Celery task
    task = generate_test_cases_task.delay(
        session_id=request.session_id,
        project_id=request.project_id,
        point_ids=request.point_ids,
        hallucination_strategy=request.hallucination_strategy
    )

    # 生成完成节点：更新会话状态（identify 时已建会话；查不到就新建，兼容直连生成）
    result = await db.execute(
        select(GenerationSession).where(GenerationSession.id == uuid.UUID(request.session_id))
    )
    session = result.scalar_one_or_none()
    if session:
        session.hallucination_strategy = request.hallucination_strategy
        session.current_step = 7
        session.updated_at = datetime.utcnow()
    else:
        db.add(GenerationSession(
            id=uuid.UUID(request.session_id),
            project_id=project_uuid,
            hallucination_strategy=request.hallucination_strategy,
            current_step=7,
            status="in_progress"
        ))
    await db.commit()

    return {
        "code": 0,
        "message": "Test case generation started",
        "data": {
            "session_id": request.session_id,
            "task_id": task.id,
            "sse_url": f"/api/sse/stream/{request.session_id}"
        }
    }


@router.get("/test-cases")
async def get_test_cases(
    project_id: str = Query(..., description="Project ID"),
    point_id: Optional[str] = Query(None, description="Filter by test point ID"),
    hallucination_status: Optional[str] = Query(
        None,
        description="Filter by hallucination status: normal, suspected, confirmed"
    ),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 7: Get generated test cases

    Retrieves all test cases for a project with optional filters and pagination.
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    query = select(TestCase).where(
        and_(
            TestCase.project_id == project_uuid,
            TestCase.is_deleted.is_(False)
        )
    )

    if point_id:
        try:
            point_uuid = uuid.UUID(point_id)
            query = query.where(TestCase.point_id == point_uuid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid point ID format")

    if hallucination_status:
        query = query.where(TestCase.hallucination_status == hallucination_status)

    query = query.order_by(TestCase.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    test_cases = result.scalars().all()

    return {
        "code": 0,
        "data": [case.to_dict() for case in test_cases]
    }


@router.get("/rules")
async def get_rules(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all test rules

    Retrieves both built-in and custom test rules with pagination.
    """
    result = await db.execute(
        select(TestRule)
        .where(TestRule.status == "active")
        .order_by(TestRule.is_builtin.desc(), TestRule.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rules = result.scalars().all()

    return {
        "code": 0,
        "data": [
            {
                "id": str(rule.id),
                "name": rule.name,
                "description": rule.description,
                "prompt_template": rule.prompt_template,
                "is_builtin": rule.is_builtin,
                "status": rule.status,
                "created_by": rule.created_by,
                "created_at": rule.created_at.isoformat() if rule.created_at else None
            }
            for rule in rules
        ]
    }


@router.post("/rules")
async def create_rule(
    request: RuleCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create custom test rule

    Creates a new custom test rule that can be used during test point identification.
    """
    # Create new rule
    rule = TestRule(
        name=request.name,
        description=request.description,
        prompt_template=request.prompt_template,
        is_builtin=False,
        status="active",
        created_by=DEFAULT_USER  # TODO: Get from auth context when authentication is implemented
    )

    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    return {
        "code": 0,
        "message": "Rule created successfully",
        "data": {
            "id": str(rule.id),
            "name": rule.name,
            "description": rule.description,
            "prompt_template": rule.prompt_template,
            "is_builtin": rule.is_builtin,
            "status": rule.status
        }
    }


def _rule_to_dict(rule: TestRule) -> dict:
    """Serialize a TestRule row for API responses"""
    return {
        "id": str(rule.id),
        "name": rule.name,
        "description": rule.description,
        "prompt_template": rule.prompt_template,
        "is_builtin": rule.is_builtin,
        "status": rule.status,
        "created_by": rule.created_by,
        "created_at": rule.created_at.isoformat() if rule.created_at else None
    }


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    request: RuleUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update custom test rule

    Only custom (non-builtin) rules can be updated.
    """
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")

    result = await db.execute(select(TestRule).where(TestRule.id == rule_uuid))
    rule = result.scalars().first()
    if not rule or rule.status != "active":
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.is_builtin:
        raise HTTPException(status_code=403, detail="Built-in rules cannot be modified")

    if request.name is not None:
        rule.name = request.name
    if request.description is not None:
        rule.description = request.description
    if request.prompt_template is not None:
        rule.prompt_template = request.prompt_template

    await db.commit()
    await db.refresh(rule)

    return {"code": 0, "message": "Rule updated successfully", "data": _rule_to_dict(rule)}


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete custom test rule (soft delete: status -> inactive)

    Only custom (non-builtin) rules can be deleted.
    """
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")

    result = await db.execute(select(TestRule).where(TestRule.id == rule_uuid))
    rule = result.scalars().first()
    if not rule or rule.status != "active":
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.is_builtin:
        raise HTTPException(status_code=403, detail="Built-in rules cannot be deleted")

    rule.status = "inactive"
    await db.commit()

    return {"code": 0, "message": "Rule deleted successfully", "data": {"id": rule_id}}


# ---------------- 生成会话（生成历史页数据源） ----------------

@router.get("/sessions")
async def list_sessions(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    status: Optional[str] = Query(None, description="Filter by status: in_progress, completed, failed"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """
    生成会话列表（生成历史页）

    会话在 identify-points 时创建、generate-cases 时更新。
    counts/tokens 从 test_point / test_case / ai_call_log 聚合。
    """
    query = select(GenerationSession)
    if project_id:
        try:
            query = query.where(GenerationSession.project_id == uuid.UUID(project_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project ID format")
    if status:
        query = query.where(GenerationSession.status == status)

    query = query.order_by(GenerationSession.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    sessions = result.scalars().all()

    data = []
    for s in sessions:
        # 聚合：该会话识别的测试点数（同项目 + 会话创建时间之后到下次会话前，简化口径：项目内全部）
        # 精确关联需要 test_point 加 session_id 外键（V1.2 再做），此处按项目+时间窗粗略统计
        pts_result = await db.execute(
            select(func.count(TestPoint.id)).where(TestPoint.project_id == s.project_id)
        )
        cases_result = await db.execute(
            select(func.count(TestCase.id)).where(
                and_(TestCase.project_id == s.project_id, TestCase.is_deleted.is_(False))
            )
        )
        tokens_result = await db.execute(
            select(func.coalesce(func.sum(AICallLog.tokens_used), 0)).where(
                AICallLog.project_id == s.project_id
            )
        )
        project_name = None
        pr = await db.execute(select(Project).where(Project.id == s.project_id))
        p = pr.scalar_one_or_none()
        if p:
            project_name = p.name

        data.append({
            "session_id": str(s.id),
            "project_id": str(s.project_id) if s.project_id else None,
            "project_name": project_name,
            "status": s.status,
            "test_points_count": pts_result.scalar() or 0,
            "test_cases_count": cases_result.scalar() or 0,
            "total_tokens": int(tokens_result.scalar() or 0),
            "start_time": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            "current_step": s.current_step,
        })

    return {"code": 0, "data": data}


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """生成会话详情：文档摘要 + 会话内识别的测试点 + 生成的用例"""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    result = await db.execute(select(GenerationSession).where(GenerationSession.id == sid))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    # 该会话时间窗内（创建→下次更新/现在）项目内的测试点与用例
    pts_result = await db.execute(
        select(TestPoint).where(
            and_(TestPoint.project_id == s.project_id,
                 TestPoint.created_at >= s.created_at)
        ).order_by(TestPoint.created_at.desc())
    )
    points = pts_result.scalars().all()

    cases_result = await db.execute(
        select(TestCase).where(
            and_(TestCase.project_id == s.project_id,
                 TestCase.is_deleted.is_(False),
                 TestCase.created_at >= s.created_at)
        ).order_by(TestCase.created_at.desc())
    )
    cases = cases_result.scalars().all()

    return {
        "code": 0,
        "data": {
            "session_id": str(s.id),
            "project_id": str(s.project_id) if s.project_id else None,
            "status": s.status,
            "document_summary": (s.document_content or "")[:500],
            "selected_rules": s.selected_rules,
            "hallucination_strategy": s.hallucination_strategy,
            "generation_mode": "comprehensive",
            "test_points": [
                {"id": str(p.id), "page_name": p.page_name, "name": p.name,
                 "type_label": p.type_label, "description": p.description}
                for p in points
            ],
            "test_cases": [
                {"id": str(c.id), "name": c.name, "priority": c.priority,
                 "is_finalized": c.is_finalized}
                for c in cases
            ],
        }
    }


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    """删除生成会话记录（仅删会话，不动已生成的测试点/用例）"""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    result = await db.execute(select(GenerationSession).where(GenerationSession.id == sid))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(s)
    await db.commit()
    return {"code": 0, "message": "Session deleted successfully", "data": {"id": session_id}}
