import asyncio
import uuid


def deploy_service(deployment_id: str) -> None:
    from services.deployment_worker import deploy_service_deployment

    asyncio.run(deploy_service_deployment(uuid.UUID(deployment_id)))


def check_container_health() -> None:
    from services.watchdog import check_once

    asyncio.run(check_once())
