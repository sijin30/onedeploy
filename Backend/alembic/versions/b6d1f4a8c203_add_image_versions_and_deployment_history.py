"""add image versions and deployment history

Revision ID: b6d1f4a8c203
Revises: a7c3e1d9f402
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6d1f4a8c203"
down_revision: Union[str, Sequence[str], None] = "a7c3e1d9f402"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column(
            "next_image_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.create_table(
        "image_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("image_tag", sa.String(length=255), nullable=False),
        sa.Column("image_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("image_tag"),
        sa.UniqueConstraint(
            "service_id",
            "version",
            name="uq_image_versions_service_version",
        ),
    )
    op.create_table(
        "deployments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=False),
        sa.Column("image_version_id", sa.UUID(), nullable=True),
        sa.Column("image_tag", sa.String(length=255), nullable=False),
        sa.Column("image_id", sa.String(length=255), nullable=True),
        sa.Column("container_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["image_version_id"], ["image_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deployments_service_created_at",
        "deployments",
        ["service_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deployments_service_created_at",
        table_name="deployments",
    )
    op.drop_table("deployments")
    op.drop_table("image_versions")
    op.drop_column("services", "next_image_version")
