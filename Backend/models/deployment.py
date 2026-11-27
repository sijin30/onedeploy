import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base


class DeploymentStatus(StrEnum):
    PENDING = "pending"
    BUILDING = "building"
    RUNNING = "running"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


_DEPLOYMENT_TRANSITIONS = {
    DeploymentStatus.PENDING: {
        DeploymentStatus.BUILDING,
        DeploymentStatus.FAILED,
    },
    DeploymentStatus.BUILDING: {
        DeploymentStatus.RUNNING,
        DeploymentStatus.FAILED,
    },
    DeploymentStatus.FAILED: {DeploymentStatus.BUILDING, DeploymentStatus.ROLLED_BACK},
    DeploymentStatus.RUNNING: {DeploymentStatus.ROLLED_BACK},
    DeploymentStatus.ROLLED_BACK: set(),
}


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("services.id", ondelete="CASCADE"),
        nullable=False,
    )
    rollback_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deployments.id", ondelete="SET NULL"),
        nullable=True,
    )
    image_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("image_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    image_tag: Mapped[str] = mapped_column(String(255), nullable=False)
    image_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queue_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default=DeploymentStatus.PENDING.value,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ports: Mapped[dict[str, int]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    environment: Mapped[dict[str, str]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    health_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    auto_heal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def transition_to(self, status: DeploymentStatus) -> None:
        current_status = DeploymentStatus(self.status)
        if status not in _DEPLOYMENT_TRANSITIONS[current_status]:
            raise ValueError(
                f"Invalid deployment transition: {current_status} -> {status}"
            )
        self.status = status.value
        self.updated_at = datetime.now(timezone.utc)
