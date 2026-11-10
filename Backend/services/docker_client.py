from typing import Any

import docker
from docker.client import DockerClient
from docker.models.containers import Container
from docker.models.images import Image


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


def list_docker_images() -> list[Image]:
    """Return images currently available in the local Docker Engine."""
    client = create_docker_client()
    try:
        return client.images.list()
    finally:
        client.close()


def list_running_containers() -> list[Container]:
    """Return containers currently running in the Docker Engine."""
    client = create_docker_client()
    try:
        return client.containers.list()
    finally:
        client.close()
