from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_current_user
from db.database import get_db
from models.incident import Incident
from models.user import User
from schemas.incident import IncidentResponse
from services.project import get_user_project
from services.service import get_project_service


router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["Incidents"],
)


@router.get("/incidents", response_model=list[IncidentResponse])
async def list_project_incidents(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_user_project(project_id, current_user.id, db)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(Incident)
        .where(Incident.project_id == project_id)
        .order_by(Incident.created_at.desc())
    )
    return result.scalars().all()


@router.get(
    "/services/{service_id}/incidents",
    response_model=list[IncidentResponse],
)
async def list_service_incidents(
    project_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_user_project(project_id, current_user.id, db)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    service = await get_project_service(service_id, project_id, db)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    result = await db.execute(
        select(Incident)
        .where(
            Incident.project_id == project_id,
            Incident.service_id == service_id,
        )
        .order_by(Incident.created_at.desc())
    )
    return result.scalars().all()
