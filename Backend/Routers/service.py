from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_current_user
from db.database import get_db
from models.user import User
from schemas.service import ServiceCreate, ServiceResponse
from services.project import get_user_project
from services.service import (
    create_service,
    get_project_services,
    get_project_service,
    delete_service as delete_service_service,
)

router = APIRouter(
    prefix="/projects/{project_id}/services",
    tags=["Services"]
)


# Create a service
@router.post("/", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_new_service(
    project_id: UUID,
    service: ServiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_user_project(project_id, current_user.id, db)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    return await create_service(service, project_id, db)


# List services
@router.get("/", response_model=list[ServiceResponse])
async def list_services(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_user_project(project_id, current_user.id, db)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    return await get_project_services(project_id, db)


# Get a specific service
@router.get("/{service_id}", response_model=ServiceResponse)
async def get_service(
    project_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_user_project(project_id, current_user.id, db)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    service = await get_project_service(service_id, project_id, db)

    if not service:
        raise HTTPException(
            status_code=404,
            detail="Service not found"
        )

    return service


# Delete a service
@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_service(
    project_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_user_project(project_id, current_user.id, db)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    deleted = await delete_service_service(service_id, project_id, db)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Service not found"
        )

    return None