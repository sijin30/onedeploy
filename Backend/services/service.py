import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.service import Service
from schemas.service import ServiceCreate


async def create_service(
    data: ServiceCreate,
    project_id: uuid.UUID,
    db: AsyncSession
):
    service = Service(
        name=data.name,
        project_id=project_id
    )

    db.add(service)
    await db.commit()
    await db.refresh(service)

    return service


async def get_project_services(
    project_id: uuid.UUID,
    db: AsyncSession
):
    result = await db.execute(
        select(Service).where(Service.project_id == project_id)
    )

    return result.scalars().all()


async def get_project_service(
    service_id: uuid.UUID,
    project_id: uuid.UUID,
    db: AsyncSession
):
    result = await db.execute(
        select(Service).where(
            Service.id == service_id,
            Service.project_id == project_id
        )
    )

    return result.scalar_one_or_none()


async def delete_service(
    service_id: uuid.UUID,
    project_id: uuid.UUID,
    db: AsyncSession
):
    service = await get_project_service(
        service_id,
        project_id,
        db
    )

    if not service:
        return False

    await db.delete(service)
    await db.commit()

    return True