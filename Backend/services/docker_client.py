from pathlib import Path
from typing import Any, Literal

import docker
from docker.client import DockerClient
from docker.models.containers import Container
from docker.models.images import Image

ContainerAction = Literal["start", "stop", "restart", "remove"]


def create_docker_client() -> DockerClient:
    """Create a client using Docker's standard environment configuration.

    The caller is responsible for closing the returned client.
    """
    return docker.from_env()


def get_docker_info() -> dict[str, Any]:
    """Return information reported by the connected Docker Engine."""
    client = create_docker_client()
    try:
        return client.info()
    finally:
        client.close()


def list_docker_images(labels: dict[str, str] | None = None) -> list[Image]:
    """Return images currently available in the local Docker Engine."""
    client = create_docker_client()
    try:
        if labels is None:
            return client.images.list()
        return client.images.list(
            filters={"label": [f"{key}={value}" for key, value in labels.items()]}
        )
    finally:
        client.close()


def list_running_containers() -> list[Container]:
    """Return containers currently running in the Docker Engine."""
    client = create_docker_client()
    try:
        return client.containers.list()
    finally:
        client.close()


def build_docker_image(
    context_path: Path,
    tag: str,
    labels: dict[str, str],
) -> Image:
    """Build and tag an image from a local Docker build context."""
    client = create_docker_client()
    try:
        image, _ = client.images.build(
            path=str(context_path),
            tag=tag,
            rm=True,
            labels=labels,
        )
        return image
    finally:
        client.close()


def run_docker_container(
    image: str,
    name: str,
    labels: dict[str, str],
    ports: dict[str, int] | None = None,
    environment: dict[str, str] | None = None,
) -> Container:
    """Start a detached container from an image."""
    client = create_docker_client()
    try:
        container = client.containers.run(
            image,
            name=name,
            detach=True,
            labels=labels,
            ports=ports or {},
            environment=environment or {},
        )
        container.reload()
        return container
    finally:
        client.close()


def list_service_containers(labels: dict[str, str]) -> list[Container]:
    """Return all containers belonging to a OneDeploy service."""
    client = create_docker_client()
    try:
        return client.containers.list(
            all=True,
            filters={
                "label": [f"{key}={value}" for key, value in labels.items()]
            },
        )
    finally:
        client.close()


def get_docker_container(container_id: str) -> Container:
    """Retrieve a container by ID."""
    client = create_docker_client()
    try:
        container = client.containers.get(container_id)
        container.reload()
        return container
    finally:
        client.close()


def manage_docker_container(
    container_id: str,
    action: ContainerAction,
) -> Container | None:
    """Apply a lifecycle action to a container; remove returns None."""
    client = create_docker_client()
    try:
        container = client.containers.get(container_id)
        if action == "start":
            container.start()
        elif action == "stop":
            container.stop()
        elif action == "restart":
            container.restart()
        else:
            container.remove()
            return None
        container.reload()
        return container
    finally:
        client.close()


def get_docker_container_logs(container_id: str) -> str:
    """Return a container's logs as decoded text."""
    client = create_docker_client()
    try:
        container = client.containers.get(container_id)
        return container.logs().decode("utf-8", errors="replace")
    finally:
        client.close()
