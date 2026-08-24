"""
Project API endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
import uuid

from app.core.database import get_db
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter()


@router.get("/", response_model=List[ProjectResponse])
async def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List all projects
    """
    query = select(Project).where(Project.is_deleted.is_(False))

    if status:
        query = query.where(Project.status == status)

    query = query.offset(skip).limit(limit).order_by(Project.created_at.desc())

    result = await db.execute(query)
    projects = result.scalars().all()

    return [ProjectResponse(**project.to_dict()) for project in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get project by ID
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(
        select(Project).where(
            and_(
                Project.id == project_uuid,
                Project.is_deleted.is_(False)
            )
        )
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectResponse(**project.to_dict())


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    project_data: ProjectCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create new project
    """
    # Check if code already exists
    result = await db.execute(
        select(Project).where(Project.code == project_data.code)
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail="Project code already exists")

    # Create new project
    project = Project(
        name=project_data.name,
        code=project_data.code,
        description=project_data.description,
        target_url=project_data.target_url,
        created_by=project_data.created_by or "system"
    )

    db.add(project)
    await db.commit()
    await db.refresh(project)

    return ProjectResponse(**project.to_dict())


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project_data: ProjectUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update project
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(
        select(Project).where(
            and_(
                Project.id == project_uuid,
                Project.is_deleted.is_(False)
            )
        )
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Update fields
    update_data = project_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)

    await db.commit()
    await db.refresh(project)

    return ProjectResponse(**project.to_dict())


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Soft delete project
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    result = await db.execute(
        select(Project).where(
            and_(
                Project.id == project_uuid,
                Project.is_deleted.is_(False)
            )
        )
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Soft delete
    project.is_deleted = True
    await db.commit()

    return {"code": 0, "message": "Project deleted successfully"}
