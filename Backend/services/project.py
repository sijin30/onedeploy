import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.project import Project
from schemas.project import ProjectCreate


async def create_project(
    data: ProjectCreate,
    user_id: uuid.UUID,
    db: AsyncSession,
):
    project = Project(
        name=data.name,
        owner_id=user_id,
    )

    db.add(project)

    await db.commit()
    await db.refresh(project)

    return project


async def get_user_projects(
    user_id: uuid.UUID,
    db: AsyncSession,
):
    result = await db.execute(
        select(Project).where(
            Project.owner_id == user_id
        )
    )

    return result.scalars().all()


async def get_user_project(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
):
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == user_id,
        )
    )

    return result.scalar_one_or_none()


async def delete_project(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
):
    project = await get_user_project(
        project_id,
        user_id,
        db,
    )

    if not project:
        return False

    await db.delete(project)
    await db.commit()

    return True
