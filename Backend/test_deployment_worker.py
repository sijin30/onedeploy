import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import docker

from models.deployment import Deployment, DeploymentStatus
from services import deployment_worker


class DeploymentWorkerTests(unittest.IsolatedAsyncioTestCase):
    def create_session_context(self, deployment, service):
        deployment_result = MagicMock()
        deployment_result.scalar_one_or_none.return_value = deployment
        service_result = MagicMock()
        service_result.scalar_one_or_none.return_value = service
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=[deployment_result, service_result]
        )
        session.commit = AsyncMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=None)
        return context, session

    async def test_redelivery_reuses_existing_container(self):
        project_id = uuid4()
        service_id = uuid4()
        deployment_id = uuid4()
        deployment = Deployment(
            id=deployment_id,
            service_id=service_id,
            image_tag="onedeploy/service:v1",
            status=DeploymentStatus.BUILDING.value,
        )
        service = SimpleNamespace(
            id=service_id,
            project_id=project_id,
            active_deployment_id=None,
        )
        context, session = self.create_session_context(deployment, service)
        container = MagicMock()
        container.id = "container-id"
        container.labels = {
            deployment_worker.DEPLOYMENT_LABEL: str(deployment_id),
        }
        container.status = "running"
        container.attrs = {"Image": "sha256:image-one"}

        with (
            patch.object(
                deployment_worker,
                "SessionLocal",
                return_value=context,
            ),
            patch.object(
                deployment_worker.asyncio,
                "to_thread",
                new=AsyncMock(return_value=container),
            ) as to_thread,
        ):
            await deployment_worker._deploy_service_deployment(deployment_id)

        self.assertEqual(to_thread.await_count, 1)
        self.assertEqual(deployment.container_id, container.id)
        self.assertEqual(deployment.status, DeploymentStatus.RUNNING)
        self.assertEqual(service.active_deployment_id, deployment_id)
        self.assertEqual(session.commit.await_count, 3)

    async def test_retry_resumes_failed_deployment(self):
        project_id = uuid4()
        service_id = uuid4()
        deployment_id = uuid4()
        deployment = Deployment(
            id=deployment_id,
            service_id=service_id,
            image_tag="onedeploy/service:v1",
            status=DeploymentStatus.FAILED.value,
        )
        service = SimpleNamespace(
            id=service_id,
            project_id=project_id,
            active_deployment_id=deployment_id,
        )
        context, _ = self.create_session_context(deployment, service)
        container = MagicMock()
        container.id = "container-id"
        container.labels = {
            deployment_worker.DEPLOYMENT_LABEL: str(deployment_id),
        }
        container.status = "running"
        container.attrs = {"Image": "sha256:image-one"}

        with (
            patch.object(
                deployment_worker,
                "SessionLocal",
                return_value=context,
            ),
            patch.object(
                deployment_worker.asyncio,
                "to_thread",
                new=AsyncMock(return_value=container),
            ),
        ):
            await deployment_worker._deploy_service_deployment(deployment_id)

        self.assertEqual(deployment.status, DeploymentStatus.RUNNING)

    async def test_pending_deployment_creates_container_and_records_state(self):
        project_id = uuid4()
        service_id = uuid4()
        deployment_id = uuid4()
        deployment = Deployment(
            id=deployment_id,
            service_id=service_id,
            image_tag="onedeploy/service:v2",
            status=DeploymentStatus.PENDING.value,
            ports={"8000/tcp": 8000},
            environment={"MODE": "test"},
        )
        service = SimpleNamespace(
            id=service_id,
            project_id=project_id,
            active_deployment_id=None,
        )
        context, session = self.create_session_context(deployment, service)
        container = MagicMock()
        container.id = "new-container"
        container.status = "running"
        container.attrs = {"Image": "sha256:image-two"}

        with (
            patch.object(
                deployment_worker,
                "SessionLocal",
                return_value=context,
            ),
            patch.object(
                deployment_worker.asyncio,
                "to_thread",
                new=AsyncMock(
                    side_effect=[
                        docker.errors.NotFound("container not found"),
                        object(),
                        None,
                        container,
                    ]
                ),
            ) as to_thread,
        ):
            await deployment_worker._deploy_service_deployment(deployment_id)

        self.assertEqual(deployment.status, DeploymentStatus.RUNNING)
        self.assertEqual(deployment.container_id, container.id)
        self.assertEqual(service.active_deployment_id, deployment_id)
        self.assertEqual(to_thread.await_count, 4)
        self.assertEqual(
            to_thread.await_args_list[2].args[1],
            {
                deployment_worker.PROJECT_LABEL: str(project_id),
                deployment_worker.SERVICE_LABEL: str(service_id),
            },
        )
        self.assertEqual(session.commit.await_count, 3)

    async def test_health_failure_marks_deployment_failed(self):
        project_id = uuid4()
        service_id = uuid4()
        deployment_id = uuid4()
        deployment = Deployment(
            id=deployment_id,
            service_id=service_id,
            image_tag="onedeploy/service:v2",
            status=DeploymentStatus.PENDING.value,
            health_url="http://localhost:8000/health",
        )
        service = SimpleNamespace(
            id=service_id,
            project_id=project_id,
            active_deployment_id=None,
        )
        context, _ = self.create_session_context(deployment, service)
        container = MagicMock()
        container.id = "new-container"
        container.status = "running"
        container.attrs = {"Image": "sha256:image-two"}

        with (
            patch.object(
                deployment_worker,
                "SessionLocal",
                return_value=context,
            ),
            patch.object(
                deployment_worker.asyncio,
                "to_thread",
                new=AsyncMock(
                    side_effect=[
                        docker.errors.NotFound("container not found"),
                        object(),
                        None,
                        container,
                        False,
                    ]
                ),
            ),
            patch.object(
                deployment_worker.settings,
                "DEPLOYMENT_HEALTH_TIMEOUT_SECONDS",
                0,
            ),
        ):
            with self.assertRaises(deployment_worker.DeploymentHealthError):
                await deployment_worker._deploy_service_deployment(
                    deployment_id
                )

        self.assertEqual(deployment.status, DeploymentStatus.FAILED)
        self.assertEqual(
            deployment.error,
            "Deployment health check timed out",
        )


if __name__ == "__main__":
    unittest.main()
