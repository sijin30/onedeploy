from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

import docker
from fastapi import APIRouter, Depends, HTTPException, status
from git import GitCommandError
from docker.models.containers import Container
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from core.dependencies import get_current_user
from db.database import get_db
from models.deployment import Deployment
from models.image_version import ImageVersion
from models.service import Service
from models.user import User
from schemas.service import (
    DockerContainerCreate,
    DockerContainerResponse,
    DockerImageResponse,
    DeploymentResponse,
    GitHubRepositoryCreate,
    ImageVersionResponse,
)
from services import docker_client
from services.project import get_user_project
from services.repository import (
    clone_github_repository,
    normalize_github_repository_url,
    repository_workspace_path,
)
from services.service import get_project_service


router = APIRouter(
    prefix="/projects/{project_id}/services/{service_id}",
    tags=["Deployment"],
)

PROJECT_LABEL = "com.onedeploy.project"
SERVICE_LABEL = "com.onedeploy.service"


def _service_labels(project_id: UUID, service_id: UUID) -> dict[str, str]:
    return {
        PROJECT_LABEL: str(project_id),
        SERVICE_LABEL: str(service_id),
    }


async def _require_service(
    project_id: UUID,
    service_id: UUID,
    current_user: User,
    db: AsyncSession,
):
    project = await get_user_project(project_id, current_user.id, db)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    service = await get_project_service(service_id, project_id, db)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


def _container_response(container: Container) -> DockerContainerResponse:
    attrs = container.attrs
    return DockerContainerResponse(
        id=container.id,
        name=container.name,
        image=attrs.get("Config", {}).get("Image", ""),
        status=container.status,
        created=attrs.get("Created", ""),
        ports=attrs.get("NetworkSettings", {}).get("Ports") or {},
    )


def _require_service_container(container: Container, labels: dict[str, str]) -> None:
    if any(container.labels.get(key) != value for key, value in labels.items()):
        raise HTTPException(status_code=404, detail="Container not found")


def _docker_error(error: docker.errors.DockerException) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Docker Engine operation failed: {error}",
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _update_deployment(
    db: AsyncSession,
    container_id: str,
    service_id: UUID,
    deployment_status: str,
) -> None:
    result = await db.execute(
        select(Deployment).where(
            Deployment.container_id == container_id,
            Deployment.service_id == service_id,
        )
    )
    deployment = result.scalar_one_or_none()
    if deployment is not None:
        deployment.status = deployment_status
        deployment.updated_at = _utcnow()
        await db.commit()


@router.post("/github", status_code=status.HTTP_201_CREATED)
async def clone_github_repository_for_service(
    project_id: UUID,
    service_id: UUID,
    repository: GitHubRepositoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    try:
        normalized_url = normalize_github_repository_url(repository.repository_url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    try:
        cloned_url, _ = await run_in_threadpool(
            clone_github_repository,
            normalized_url,
            str(project_id),
            str(service_id),
        )
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except GitCommandError as error:
        raise HTTPException(
            status_code=422,
            detail=f"Unable to clone GitHub repository: {error}",
        ) from error

    return {"repository_url": cloned_url, "status": "cloned"}


@router.post("/build", response_model=DockerImageResponse)
async def build_service_image(
    project_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    context_path = repository_workspace_path(str(project_id), str(service_id))
    if not context_path.is_dir() or not (context_path / "Dockerfile").is_file():
        raise HTTPException(
            status_code=409,
            detail="Clone a GitHub repository containing a Dockerfile first",
        )

    result = await db.execute(
        select(Service)
        .where(Service.id == service_id, Service.project_id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    service = result.scalar_one()
    version = service.next_image_version
    service.next_image_version += 1
    image_repository = f"onedeploy/{project_id.hex}-{service_id.hex}"
    image_tag = f"{image_repository}:v{version}"
    latest_tag = f"{image_repository}:latest"
    image_version = ImageVersion(
        service_id=service_id,
        version=version,
        image_tag=image_tag,
        status="building",
    )
    db.add(image_version)
    await db.commit()

    labels = _service_labels(project_id, service_id)
    try:
        image = await run_in_threadpool(
            docker_client.build_docker_image,
            context_path,
            image_tag,
            labels,
        )
    except docker.errors.DockerException as error:
        image_version.status = "failed"
        image_version.error = str(error)
        image_version.completed_at = _utcnow()
        await db.commit()
        raise _docker_error(error) from error

    result = await db.execute(
        select(Service)
        .where(Service.id == service_id, Service.project_id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    result.scalar_one()
    image_version.image_id = image.id
    image_version.status = "built"
    image_version.completed_at = _utcnow()
    result = await db.execute(
        select(ImageVersion)
        .where(
            ImageVersion.service_id == service_id,
            ImageVersion.status == "built",
        )
        .order_by(ImageVersion.version.desc())
        .limit(1)
    )
    newest_version = result.scalar_one_or_none()
    if newest_version and newest_version.version == version:
        try:
            await run_in_threadpool(
                docker_client.tag_docker_image,
                image.id,
                image_repository,
                "latest",
            )
        except docker.errors.DockerException as error:
            image_version.status = "failed"
            image_version.error = str(error)
            await db.commit()
            raise _docker_error(error) from error
    await db.commit()
    return DockerImageResponse(
        id=image.id,
        tags=sorted(set((image.tags or []) + [image_tag, latest_tag])),
    )


@router.get(
    "/image-versions",
    response_model=list[ImageVersionResponse],
)
async def list_service_image_versions(
    project_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    result = await db.execute(
        select(ImageVersion)
        .where(ImageVersion.service_id == service_id)
        .order_by(ImageVersion.version.desc())
    )
    return result.scalars().all()


@router.get("/deployments", response_model=list[DeploymentResponse])
async def list_service_deployments(
    project_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    result = await db.execute(
        select(Deployment)
        .where(Deployment.service_id == service_id)
        .order_by(Deployment.created_at.desc())
    )
    return result.scalars().all()


@router.get("/images", response_model=list[DockerImageResponse])
async def list_service_images(
    project_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    try:
        images = await run_in_threadpool(
            docker_client.list_docker_images,
            _service_labels(project_id, service_id),
        )
    except docker.errors.DockerException as error:
        raise _docker_error(error) from error
    return [DockerImageResponse(id=image.id, tags=image.tags) for image in images]


@router.post(
    "/containers",
    response_model=DockerContainerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_service_container(
    project_id: UUID,
    service_id: UUID,
    request: DockerContainerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    labels = _service_labels(project_id, service_id)
    if request.health_url:
        labels["com.onedeploy.health-url"] = request.health_url
    labels["com.onedeploy.auto-heal"] = str(request.auto_heal).lower()

    image_version = None
    if request.image_version is not None:
        result = await db.execute(
            select(ImageVersion).where(
                ImageVersion.service_id == service_id,
                ImageVersion.version == request.image_version,
            )
        )
        image_version = result.scalar_one_or_none()
        if image_version is None:
            raise HTTPException(status_code=404, detail="Image version not found")
        if image_version.status != "built":
            raise HTTPException(
                status_code=409,
                detail="Image version is not available for deployment",
            )
        image_tag = image_version.image_tag
    else:
        latest_tag = f"onedeploy/{project_id.hex}-{service_id.hex}:latest"
        result = await db.execute(
            select(ImageVersion)
            .where(
                ImageVersion.service_id == service_id,
                ImageVersion.status == "built",
            )
            .order_by(ImageVersion.version.desc())
            .limit(1)
        )
        image_version = result.scalar_one_or_none()
        image_tag = image_version.image_tag if image_version else latest_tag

    deployment = Deployment(
        service_id=service_id,
        image_version_id=image_version.id if image_version else None,
        image_tag=image_tag,
        image_id=image_version.image_id if image_version else None,
        status="starting",
    )
    db.add(deployment)
    await db.commit()
    try:
        container = await run_in_threadpool(
            docker_client.run_docker_container,
            image_tag,
            f"od-{project_id.hex[:8]}-{service_id.hex[:8]}-{uuid4().hex[:8]}",
            labels,
            request.ports,
            request.environment,
        )
    except docker.errors.ImageNotFound as error:
        deployment.status = "failed"
        deployment.error = str(error)
        deployment.updated_at = _utcnow()
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail="Build the service image version before starting a container",
        ) from error
    except docker.errors.DockerException as error:
        deployment.status = "failed"
        deployment.error = str(error)
        deployment.updated_at = _utcnow()
        await db.commit()
        raise _docker_error(error) from error
    deployment.container_id = container.id
    deployment.image_id = container.attrs.get("Image", deployment.image_id)
    deployment.status = container.status
    deployment.updated_at = _utcnow()
    await db.commit()
    return _container_response(container)


@router.get("/containers", response_model=list[DockerContainerResponse])
async def list_service_containers(
    project_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    try:
        containers = await run_in_threadpool(
            docker_client.list_service_containers,
            _service_labels(project_id, service_id),
        )
    except docker.errors.DockerException as error:
        raise _docker_error(error) from error
    return [_container_response(container) for container in containers]


@router.get("/containers/{container_id}/logs")
async def get_service_container_logs(
    project_id: UUID,
    service_id: UUID,
    container_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    try:
        container = await run_in_threadpool(
            docker_client.get_docker_container, container_id
        )
        _require_service_container(
            container, _service_labels(project_id, service_id)
        )
        logs = await run_in_threadpool(
            docker_client.get_docker_container_logs, container_id
        )
    except docker.errors.NotFound as error:
        raise HTTPException(status_code=404, detail="Container not found") from error
    except docker.errors.DockerException as error:
        raise _docker_error(error) from error
    return {"container_id": container_id, "logs": logs}


@router.post(
    "/containers/{container_id}/{action}",
    response_model=DockerContainerResponse,
)
async def manage_service_container(
    project_id: UUID,
    service_id: UUID,
    container_id: str,
    action: Literal["start", "stop", "restart"],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    try:
        container = await run_in_threadpool(
            docker_client.get_docker_container, container_id
        )
        _require_service_container(
            container, _service_labels(project_id, service_id)
        )
        container = await run_in_threadpool(
            docker_client.manage_docker_container, container_id, action
        )
        await _update_deployment(db, container_id, service_id, container.status)
    except docker.errors.NotFound as error:
        raise HTTPException(status_code=404, detail="Container not found") from error
    except docker.errors.DockerException as error:
        raise _docker_error(error) from error
    return _container_response(container)


@router.delete(
    "/containers/{container_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_service_container(
    project_id: UUID,
    service_id: UUID,
    container_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    try:
        container = await run_in_threadpool(
            docker_client.get_docker_container, container_id
        )
        _require_service_container(
            container, _service_labels(project_id, service_id)
        )
        await run_in_threadpool(
            docker_client.manage_docker_container, container_id, "remove"
        )
        await _update_deployment(db, container_id, service_id, "removed")
    except docker.errors.NotFound as error:
        raise HTTPException(status_code=404, detail="Container not found") from error
    except docker.errors.DockerException as error:
        raise _docker_error(error) from error
