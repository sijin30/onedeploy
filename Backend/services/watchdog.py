import asyncio
import logging
import socket
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone

import docker
from sqlalchemy import or_, select

from core.config import settings
from db.database import SessionLocal
from models.incident import Incident
from models.service import Service
from services import docker_client


logger = logging.getLogger("onedeploy.watchdog")
PROJECT_LABEL = "com.onedeploy.project"
SERVICE_LABEL = "com.onedeploy.service"
HEALTH_URL_LABEL = "com.onedeploy.health-url"
HEALTH_EXCLUDED_LABEL = "com.onedeploy.auto-heal"
DEPLOYMENT_LABEL = "com.onedeploy.deployment"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def check_http_health(url: str, timeout: float = 2.0) -> bool:
    if not url:
        return True
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (OSError, urllib.error.URLError, socket.timeout):
        return False


def assess_container(container) -> tuple[bool, str]:
    if container.status not in {"running", "restarting"}:
        return False, f"Container status is {container.status}"

    if container.labels.get(HEALTH_EXCLUDED_LABEL, "").lower() == "false":
        return True, "Container excluded from automatic healing"

    health_url = container.labels.get(HEALTH_URL_LABEL)
    if health_url and not check_http_health(health_url):
        return False, f"Health endpoint failed: {health_url}"

    try:
        stats = docker_client.get_docker_container_stats(container.id)
        if stats["memory_percent"] >= settings.WATCHDOG_MEMORY_PERCENT_THRESHOLD:
            return (
                False,
                f"Memory usage is {stats['memory_percent']}%",
            )
    except docker.errors.DockerException as error:
        return False, f"Unable to read container resource usage: {error}"

    return True, "Healthy"


async def _is_active_deployment(container) -> bool:
    async with SessionLocal() as db:
        result = await db.execute(
            select(Service.active_deployment_id).where(
                Service.id == uuid.UUID(container.labels[SERVICE_LABEL])
            )
        )
        active_deployment_id = result.scalar_one_or_none()

    return (
        active_deployment_id is None
        or container.labels.get(DEPLOYMENT_LABEL) == str(active_deployment_id)
    )


async def _record_incident(
    container,
    detection: str,
    action: str | None = None,
    outcome: str | None = None,
    failed_checks: int = 0,
    restart_attempts: int = 0,
    status: str = "open",
) -> Incident:
    async with SessionLocal() as db:
        result = await db.execute(
            select(Incident).where(
                Incident.container_id == container.id,
                or_(
                    Incident.status == "open",
                    Incident.status == "escalated",
                ),
            )
        )
        incident = result.scalar_one_or_none()
        if incident is None:
            incident = Incident(
                project_id=uuid.UUID(container.labels[PROJECT_LABEL]),
                service_id=uuid.UUID(container.labels[SERVICE_LABEL]),
                container_id=container.id,
                status=status,
                detection=detection,
                action=action,
                outcome=outcome,
                failed_checks=failed_checks,
                restart_attempts=restart_attempts,
            )
            db.add(incident)
        else:
            incident.detection = detection
            incident.action = action
            incident.outcome = outcome
            incident.failed_checks = failed_checks
            incident.restart_attempts = restart_attempts
            incident.status = status
            incident.updated_at = _utcnow()

        await db.commit()
        await db.refresh(incident)
        return incident


async def check_once() -> None:
    try:
        all_containers = await asyncio.to_thread(
            docker_client.list_all_containers
        )
    except docker.errors.DockerException as error:
        logger.error("Watchdog could not list service containers: %s", error)
        return

    for container in all_containers:
        if (
            PROJECT_LABEL not in container.labels
            or SERVICE_LABEL not in container.labels
        ):
            continue
        if not await _is_active_deployment(container):
            continue

        healthy, detection = await asyncio.to_thread(assess_container, container)
        container_id = container.id

        if healthy:
            async with SessionLocal() as db:
                result = await db.execute(
                    select(Incident).where(
                        Incident.container_id == container_id,
                        or_(
                            Incident.status == "open",
                            Incident.status == "escalated",
                        ),
                    )
                )
                incident = result.scalar_one_or_none()
                if incident is not None:
                    incident.status = "resolved"
                    incident.outcome = "Recovered; no restart required"
                    incident.updated_at = _utcnow()
                    await db.commit()
            continue

        async with SessionLocal() as db:
            result = await db.execute(
                select(Incident).where(
                    Incident.container_id == container_id,
                    or_(
                        Incident.status == "open",
                        Incident.status == "escalated",
                    ),
                )
            )
            active_incident = result.scalar_one_or_none()
        failed = (
            active_incident.failed_checks + 1
            if active_incident is not None
            else 1
        )
        restart_attempts = (
            active_incident.restart_attempts
            if active_incident is not None
            else 0
        )
        if failed < settings.WATCHDOG_FAILED_CHECKS:
            await _record_incident(
                container,
                detection=detection,
                failed_checks=failed,
                restart_attempts=restart_attempts,
            )
            continue

        if restart_attempts >= settings.WATCHDOG_MAX_RESTART_ATTEMPTS:
            await _record_incident(
                container,
                detection=detection,
                action="Restart suppressed",
                outcome="Restart limit reached; circuit breaker open",
                failed_checks=failed,
                restart_attempts=restart_attempts,
                status="escalated",
            )
            continue

        await _record_incident(
            container,
            detection=detection,
            action="Restart container",
            outcome="Restart in progress",
            failed_checks=failed,
            restart_attempts=restart_attempts,
        )

        try:
            await asyncio.sleep(1)
            restarted = await asyncio.to_thread(
                docker_client.manage_docker_container,
                container_id,
                "restart",
            )
            await asyncio.sleep(2)
            rechecked = await asyncio.to_thread(
                docker_client.get_docker_container,
                container_id,
            )
            recovered, outcome = await asyncio.to_thread(
                assess_container, rechecked
            )
            new_attempt_count = restart_attempts + 1
            await _record_incident(
                container,
                detection=detection,
                action="Restart container",
                outcome=(
                    f"Restart succeeded; health recheck: {outcome}"
                    if recovered
                    else f"Restart completed; health recheck failed: {outcome}"
                ),
                failed_checks=failed,
                restart_attempts=new_attempt_count,
                status="resolved" if recovered else "open",
            )
            if recovered:
                logger.info("Container %s recovered after restart", container_id)
            else:
                logger.warning(
                    "Container %s remains unhealthy after restart", container_id
                )
        except docker.errors.DockerException as error:
            new_attempt_count = restart_attempts + 1
            await _record_incident(
                container,
                detection=detection,
                action="Restart container",
                outcome=f"Restart failed: {error}",
                failed_checks=failed,
                restart_attempts=new_attempt_count,
            )
            logger.error("Restart failed for container %s: %s", container_id, error)
