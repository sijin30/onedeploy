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


class DockerContainerResponse(BaseModel):
    id: str
    name: str
    image: str
    status: str
    created: str
    ports: dict[str, object]