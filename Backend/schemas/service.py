import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ServiceCreate(BaseModel):
    name: str


class ServiceResponse(BaseModel):
    id: uuid.UUID
    name: str
    project_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class GitHubRepositoryCreate(BaseModel):
    repository_url: str


class DockerContainerCreate(BaseModel):
    ports: dict[str, int] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)
    health_url: str | None = Field(default=None)
    auto_heal: bool = Field(default=True)
    image_version: int | None = Field(default=None, ge=1)

    @field_validator("ports")
    @classmethod
    def validate_ports(cls, ports: dict[str, int]) -> dict[str, int]:
        for container_port, host_port in ports.items():
            if (
                not container_port.rpartition("/")[0].isdigit()
                or container_port.rpartition("/")[2] not in {"tcp", "udp"}
                or not 1 <= int(container_port.rpartition("/")[0]) <= 65535
                or not 1 <= host_port <= 65535
            ):
                raise ValueError("Ports must map valid container ports to host ports")
        return ports


class DockerImageResponse(BaseModel):
    id: str
    tags: list[str]


class ImageVersionResponse(BaseModel):
    id: uuid.UUID
    service_id: uuid.UUID
    version: int
    image_tag: str
    image_id: str | None
    status: str
    error: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class DeploymentResponse(BaseModel):
    id: uuid.UUID
    service_id: uuid.UUID
    image_version_id: uuid.UUID | None
    rollback_of_id: uuid.UUID | None
    image_tag: str
    image_id: str | None
    container_id: str | None
    queue_job_id: str | None
    status: str
    error: str | None
    ports: dict[str, int]
    environment: dict[str, str]
    health_url: str | None
    auto_heal: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeploymentJobResponse(BaseModel):
    deployment_id: uuid.UUID
    job_id: str
    job_status: str


class DockerContainerResponse(BaseModel):
    id: str
    name: str
    image: str
    status: str
    created: str
    ports: dict[str, object]