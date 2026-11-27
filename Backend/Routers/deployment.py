from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

import docker
from fastapi import APIRouter, Depends, HTTPException, status
from git import GitCommandError
from docker.models.containers import Container
from redis.exceptions import RedisError
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq import Retry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from core.dependencies import get_current_user
from db.database import get_db
from models.deployment import Deployment, DeploymentStatus
from models.image_version import ImageVersion
from models.service import Service
from models.user import User
from schemas.service import (
    DockerContainerCreate,
    DockerContainerResponse,
    DockerImageResponse,
    DeploymentJobResponse,
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
from services.queue import deployment_queue, redis_connection
from services.tasks import deploy_service


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


async def _enqueue_deployment(
    deployment: Deployment,
    db: AsyncSession,
) -> None:
    try:
        job = deployment_queue.enqueue(
            deploy_service,
            str(deployment.id),
            job_id=str(deployment.id),
            retry=Retry(max=2, interval=[5, 15]),
        )
        deployment.queue_job_id = job.id
        await db.commit()
    except (RedisError, OSError) as error:
        deployment.transition_to(DeploymentStatus.FAILED)
        deployment.error = f"Unable to enqueue deployment: {error}"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Deployment queue is unavailable",
        ) from error


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


@router.get(
    "/deployments/{deployment_id}/job",
    response_model=DeploymentJobResponse,
)
async def get_service_deployment_job(
    project_id: UUID,
    service_id: UUID,
    deployment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    result = await db.execute(
        select(Deployment).where(
            Deployment.id == deployment_id,
            Deployment.service_id == service_id,
        )
    )
    deployment = result.scalar_one_or_none()
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if deployment.queue_job_id is None:
        raise HTTPException(status_code=404, detail="Queue job not found")

    try:
        job = Job.fetch(
            deployment.queue_job_id,
            connection=redis_connection,
        )
    except NoSuchJobError as error:
        raise HTTPException(status_code=404, detail="Queue job not found") from error

    job_status = job.get_status(refresh=True)
    return DeploymentJobResponse(
        deployment_id=deployment.id,
        job_id=job.id,
        job_status=job_status.value,
    )


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
    response_model=DeploymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_service_container(
    project_id: UUID,
    service_id: UUID,
    request: DockerContainerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
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
        if image_version is None:
            raise HTTPException(
                status_code=409,
                detail="Build the service image before starting a deployment",
            )
        image_tag = image_version.image_tag

    deployment = Deployment(
        id=uuid4(),
        service_id=service_id,
        image_version_id=image_version.id if image_version else None,
        image_tag=image_tag,
        image_id=image_version.image_id if image_version else None,
        status=DeploymentStatus.PENDING.value,
        ports=request.ports,
        environment=request.environment,
        health_url=request.health_url,
        auto_heal=request.auto_heal,
    )
    db.add(deployment)
    await db.commit()
    await _enqueue_deployment(deployment, db)
    return deployment


@router.post(
    "/deployments/{deployment_id}/rollback",
    response_model=DeploymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rollback_service_deployment(
    project_id: UUID,
    service_id: UUID,
    deployment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_service(project_id, service_id, current_user, db)
    result = await db.execute(
        select(Deployment).where(
            Deployment.id == deployment_id,
            Deployment.service_id == service_id,
        )
    )
    deployment_to_rollback = result.scalar_one_or_none()
    if deployment_to_rollback is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if deployment_to_rollback.status in {
        DeploymentStatus.PENDING,
        DeploymentStatus.BUILDING,
    }:
        raise HTTPException(
            status_code=409,
            detail="Wait for the deployment to finish before rolling it back",
        )
    if deployment_to_rollback.status == DeploymentStatus.ROLLED_BACK:
        raise HTTPException(
            status_code=409,
            detail="Deployment has already been rolled back",
        )
    result = await db.execute(
        select(Deployment).where(
            Deployment.rollback_of_id == deployment_to_rollback.id,
            Deployment.status.in_(
                [
                    DeploymentStatus.PENDING,
                    DeploymentStatus.BUILDING,
                    DeploymentStatus.RUNNING,
                ]
            ),
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="A rollback for this deployment is already in progress",
        )

    result = await db.execute(
        select(Deployment)
        .where(
            Deployment.service_id == service_id,
            Deployment.created_at < deployment_to_rollback.created_at,
            Deployment.status == DeploymentStatus.RUNNING,
            Deployment.image_version_id.is_not(None),
        )
        .order_by(Deployment.created_at.desc())
        .limit(1)
    )
    known_good = result.scalar_one_or_none()
    if known_good is None:
        raise HTTPException(
            status_code=409,
            detail="No previous successful deployment is available to roll back to",
        )

    rollback = Deployment(
        id=uuid4(),
        service_id=service_id,
        image_version_id=known_good.image_version_id,
        rollback_of_id=deployment_to_rollback.id,
        image_tag=known_good.image_tag,
        image_id=known_good.image_id,
        status=DeploymentStatus.PENDING.value,
        ports=known_good.ports,
        environment=known_good.environment,
        health_url=known_good.health_url,
        auto_heal=known_good.auto_heal,
    )
    db.add(rollback)
    await db.commit()
    await _enqueue_deployment(rollback, db)
    return rollback


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
    except docker.errors.NotFound as error:
        raise HTTPException(status_code=404, detail="Container not found") from error
    except docker.errors.DockerException as error:
        raise _docker_error(error) from error
