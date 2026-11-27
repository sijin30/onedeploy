import asyncio
import hashlib
import uuid

import docker
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from core.config import settings
from db.database import SessionLocal, engine
from models.deployment import Deployment, DeploymentStatus
from models.service import Service
from services import docker_client
from services.watchdog import check_http_health

PROJECT_LABEL = "com.onedeploy.project"
SERVICE_LABEL = "com.onedeploy.service"
DEPLOYMENT_LABEL = "com.onedeploy.deployment"


async def deploy_service_deployment(deployment_id: uuid.UUID) -> None:
    lock_key = int.from_bytes(
        hashlib.sha256(deployment_id.bytes).digest()[:8],
        byteorder="big",
        signed=True,
    )
    async with engine.connect() as lock_connection:
        acquired = await lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        await lock_connection.commit()
        if not acquired:
            return
        try:
            await _deploy_service_deployment(deployment_id)
        finally:
            try:
                await lock_connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
                await lock_connection.commit()
            except SQLAlchemyError:
                await lock_connection.invalidate()
                raise


async def _deploy_service_deployment(deployment_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(Deployment)
            .where(Deployment.id == deployment_id)
            .with_for_update()
        )
        deployment = result.scalar_one_or_none()
        if deployment is None or deployment.status in {
            DeploymentStatus.RUNNING,
            DeploymentStatus.ROLLED_BACK,
        }:
            return

        if deployment.status == DeploymentStatus.FAILED:
            deployment.transition_to(DeploymentStatus.BUILDING)
            await db.commit()

        service_result = await db.execute(
            select(Service).where(Service.id == deployment.service_id)
        )
        service = service_result.scalar_one_or_none()
        if service is None:
            deployment.transition_to(DeploymentStatus.FAILED)
            deployment.error = "Service no longer exists"
            await db.commit()
            return

        if deployment.status == DeploymentStatus.PENDING:
            deployment.transition_to(DeploymentStatus.BUILDING)
        await db.commit()

        labels = {
            PROJECT_LABEL: str(service.project_id),
            SERVICE_LABEL: str(service.id),
            DEPLOYMENT_LABEL: str(deployment.id),
        }
        container_name = f"od-{deployment.id.hex}"
        try:
            try:
                container = await asyncio.to_thread(
                    docker_client.get_docker_container,
                    container_name,
                )
                if container.labels.get(DEPLOYMENT_LABEL) != str(deployment.id):
                    raise docker.errors.DockerException(
                        "A container with the deployment name already exists"
                    )
            except docker.errors.NotFound:
                await asyncio.to_thread(
                    docker_client.get_docker_image,
                    deployment.image_tag,
                )
                service.active_deployment_id = deployment.id
                await db.commit()
                await asyncio.to_thread(
                    docker_client.stop_service_containers,
                    {
                        PROJECT_LABEL: str(service.project_id),
                        SERVICE_LABEL: str(service.id),
                    },
                )
                container = await asyncio.to_thread(
                    docker_client.run_docker_container,
                    deployment.image_tag,
                    container_name,
                    {
                        **labels,
                        "com.onedeploy.auto-heal": str(
                            deployment.auto_heal
                        ).lower(),
                        **(
                            {"com.onedeploy.health-url": deployment.health_url}
                            if deployment.health_url
                            else {}
                        ),
                    },
                    deployment.ports,
                    deployment.environment,
                )
            else:
                service.active_deployment_id = deployment.id
                await db.commit()

            deployment.container_id = container.id
            deployment.image_id = container.attrs.get(
                "Image",
                deployment.image_id,
            )
            if container.status != "running":
                deployment.transition_to(DeploymentStatus.FAILED)
                deployment.error = (
                    f"Container did not reach running state: {container.status}"
                )
            else:
                if deployment.health_url:
                    loop = asyncio.get_running_loop()
                    deadline = (
                        loop.time()
                        + settings.DEPLOYMENT_HEALTH_TIMEOUT_SECONDS
                    )
                    while True:
                        healthy = await asyncio.to_thread(
                            check_http_health,
                            deployment.health_url,
                        )
                        if healthy:
                            break
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            raise DeploymentHealthError(
                                "Deployment health check timed out"
                            )
                        await asyncio.sleep(min(2, remaining))
                deployment.transition_to(DeploymentStatus.RUNNING)
                if deployment.rollback_of_id is not None:
                    rollback_result = await db.execute(
                        select(Deployment).where(
                            Deployment.id == deployment.rollback_of_id
                        )
                    )
                    rollback_target = rollback_result.scalar_one_or_none()
                    if (
                        rollback_target is not None
                        and rollback_target.status
                        in {
                            DeploymentStatus.RUNNING,
                            DeploymentStatus.FAILED,
                        }
                    ):
                        rollback_target.transition_to(
                            DeploymentStatus.ROLLED_BACK
                        )
            await db.commit()
        except docker.errors.DockerException as error:
            if deployment.status == DeploymentStatus.BUILDING:
                deployment.transition_to(DeploymentStatus.FAILED)
            deployment.error = str(error)
            await db.commit()
            raise
        except DeploymentHealthError as error:
            if deployment.status == DeploymentStatus.BUILDING:
                deployment.transition_to(DeploymentStatus.FAILED)
            deployment.error = str(error)
            await db.commit()
            raise


class DeploymentHealthError(Exception):
    pass
