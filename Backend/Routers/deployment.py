from typing import Literal
from uuid import UUID, uuid4

import docker
from fastapi import APIRouter, Depends, HTTPException, status
from git import GitCommandError
from docker.models.containers import Container
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from core.dependencies import get_current_user
from db.database import get_db
from models.user import User
from schemas.service import (
    DockerContainerCreate,
    DockerContainerResponse,
    DockerImageResponse,
    GitHubRepositoryCreate,
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

    labels = _service_labels(project_id, service_id)
    image_tag = f"onedeploy/{project_id.hex}-{service_id.hex}:latest"
    try:
        image = await run_in_threadpool(
            docker_client.build_docker_image,
            context_path,
            image_tag,
            labels,
        )
    except docker.errors.DockerException as error:
        raise _docker_error(error) from error

    return DockerImageResponse(id=image.id, tags=image.tags)


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
    image_tag = f"onedeploy/{project_id.hex}-{service_id.hex}:latest"
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
        raise HTTPException(
            status_code=409,
            detail="Build the service image before starting a container",
        ) from error
    except docker.errors.DockerException as error:
        raise _docker_error(error) from error
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
