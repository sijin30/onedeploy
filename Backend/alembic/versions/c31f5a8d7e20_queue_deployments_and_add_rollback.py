"""queue deployments and add rollback metadata

Revision ID: c31f5a8d7e20
Revises: b6d1f4a8c203
Create Date: 2026-11-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c31f5a8d7e20"
down_revision: Union[str, Sequence[str], None] = "b6d1f4a8c203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deployments",
        sa.Column("rollback_of_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "deployments",
        sa.Column("queue_job_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "deployments",
        sa.Column(
            "ports",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        "deployments",
        sa.Column(
            "environment",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        "deployments",
        sa.Column("health_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "deployments",
        sa.Column(
            "auto_heal",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_deployments_rollback_of_id_deployments",
        "deployments",
        "deployments",
        ["rollback_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "services",
        sa.Column("active_deployment_id", sa.UUID(), nullable=True),
    )
    op.execute(
        """
        UPDATE deployments
        SET status = CASE
            WHEN status = 'failed' THEN 'failed'
            WHEN status = 'rolled_back' THEN 'rolled_back'
            ELSE 'running'
        END
        """
    )


def downgrade() -> None:
    op.drop_column("services", "active_deployment_id")
    op.drop_constraint(
        "fk_deployments_rollback_of_id_deployments",
        "deployments",
        type_="foreignkey",
    )
    op.drop_column("deployments", "auto_heal")
    op.drop_column("deployments", "health_url")
    op.drop_column("deployments", "environment")
    op.drop_column("deployments", "ports")
    op.drop_column("deployments", "queue_job_id")
    op.drop_column("deployments", "rollback_of_id")
