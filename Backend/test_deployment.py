import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from Routers import deployment
from models.deployment import Deployment, DeploymentStatus
from schemas.service import DockerContainerCreate


class DeploymentTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_service_image_allocates_and_tags_version(self):
        project_id = uuid4()
        service_id = uuid4()
        service = SimpleNamespace(next_image_version=1)
        query_result = MagicMock()
        query_result.scalar_one.return_value = service
        latest_version_result = MagicMock()
        latest_version_result.scalar_one_or_none.side_effect = (
            lambda: db.add.call_args.args[0]
        )
        db = MagicMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                query_result,
                query_result,
                latest_version_result,
            ]
        )
        db.commit = AsyncMock()
        image = SimpleNamespace(
            id="sha256:image-one",
            tags=[f"onedeploy/{project_id.hex}-{service_id.hex}:v1"],
        )
        current_user = SimpleNamespace(id=uuid4())

        with (
            patch.object(deployment, "_require_service", new=AsyncMock()),
            patch.object(
                deployment,
                "repository_workspace_path",
                return_value=Path("repository"),
            ),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=True),
            patch.object(
                deployment,
                "run_in_threadpool",
                new=AsyncMock(side_effect=[image, None]),
            ) as run_in_threadpool,
        ):
            result = await deployment.build_service_image(
                project_id,
                service_id,
                db,
                current_user,
            )

        self.assertEqual(service.next_image_version, 2)
        image_version = db.add.call_args.args[0]
        self.assertEqual(image_version.version, 1)
        self.assertEqual(image_version.image_tag, image.tags[0])
        self.assertEqual(image_version.image_id, image.id)
        self.assertEqual(image_version.status, "built")
        self.assertEqual(
            result.tags,
            sorted(
                [
                    image.tags[0],
                    f"onedeploy/{project_id.hex}-{service_id.hex}:latest",
                ]
            ),
        )
        self.assertEqual(run_in_threadpool.await_count, 2)
        self.assertEqual(
            run_in_threadpool.await_args_list[1].args[1:],
            (
                image.id,
                f"onedeploy/{project_id.hex}-{service_id.hex}",
                "latest",
            ),
        )

    async def test_container_creation_enqueues_requested_image_version(self):
        project_id = uuid4()
        service_id = uuid4()
        image_version = SimpleNamespace(
            id=uuid4(),
            image_tag=f"onedeploy/{project_id.hex}-{service_id.hex}:v4",
            image_id="sha256:image-four",
            status="built",
        )
        query_result = MagicMock()
        query_result.scalar_one_or_none.return_value = image_version
        db = MagicMock()
        db.execute = AsyncMock(return_value=query_result)
        db.add = MagicMock()
        db.commit = AsyncMock()
        current_user = SimpleNamespace(id=uuid4())

        with (
            patch.object(deployment, "_require_service", new=AsyncMock()),
            patch.object(
                deployment.deployment_queue,
                "enqueue",
                return_value=SimpleNamespace(id="queue-job-id"),
            ) as enqueue,
        ):
            result = await deployment.create_service_container(
                project_id,
                service_id,
                DockerContainerCreate(image_version=4),
                db,
                current_user,
            )

        queued_deployment = db.add.call_args.args[0]
        self.assertEqual(queued_deployment.image_version_id, image_version.id)
        self.assertEqual(queued_deployment.image_tag, image_version.image_tag)
        self.assertEqual(queued_deployment.status, "pending")
        self.assertEqual(queued_deployment.ports, {})
        self.assertEqual(queued_deployment.environment, {})
        self.assertEqual(result.id, queued_deployment.id)
        enqueue.assert_called_once()
        self.assertEqual(queued_deployment.queue_job_id, "queue-job-id")
        self.assertEqual(
            enqueue.call_args.kwargs["job_id"],
            str(queued_deployment.id),
        )

    async def test_default_container_creation_queues_latest_immutable_version(self):
        project_id = uuid4()
        service_id = uuid4()
        image_version = SimpleNamespace(
            id=uuid4(),
            image_tag=f"onedeploy/{project_id.hex}-{service_id.hex}:v7",
            image_id="sha256:image-seven",
            status="built",
        )
        query_result = MagicMock()
        query_result.scalar_one_or_none.return_value = image_version
        db = MagicMock()
        db.execute = AsyncMock(return_value=query_result)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with (
            patch.object(deployment, "_require_service", new=AsyncMock()),
            patch.object(
                deployment.deployment_queue,
                "enqueue",
                return_value=SimpleNamespace(id="queue-job-id"),
            ) as enqueue,
        ):
            result = await deployment.create_service_container(
                project_id,
                service_id,
                DockerContainerCreate(),
                db,
                SimpleNamespace(id=uuid4()),
            )

        self.assertEqual(result.image_tag, image_version.image_tag)
        enqueue.assert_called_once()

    async def test_rollback_queues_previous_successful_deployment(self):
        project_id = uuid4()
        service_id = uuid4()
        target = SimpleNamespace(
            id=uuid4(),
            status="failed",
            created_at="2026-11-26T00:00:00Z",
        )
        known_good = SimpleNamespace(
            id=uuid4(),
            image_version_id=uuid4(),
            image_tag=f"onedeploy/{project_id.hex}-{service_id.hex}:v1",
            image_id="sha256:image-one",
            ports={"8000/tcp": 8000},
            environment={"MODE": "production"},
            health_url="http://localhost:8000/health",
            auto_heal=False,
        )
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target
        existing_rollback_result = MagicMock()
        existing_rollback_result.scalar_one_or_none.return_value = None
        known_good_result = MagicMock()
        known_good_result.scalar_one_or_none.return_value = known_good
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                target_result,
                existing_rollback_result,
                known_good_result,
            ]
        )
        db.add = MagicMock()
        db.commit = AsyncMock()

        with (
            patch.object(deployment, "_require_service", new=AsyncMock()),
            patch.object(
                deployment.deployment_queue,
                "enqueue",
                return_value=SimpleNamespace(id="rollback-job-id"),
            ) as enqueue,
        ):
            result = await deployment.rollback_service_deployment(
                project_id,
                service_id,
                target.id,
                db,
                SimpleNamespace(id=uuid4()),
            )

        rollback = db.add.call_args.args[0]
        self.assertEqual(rollback.rollback_of_id, target.id)
        self.assertEqual(rollback.image_version_id, known_good.image_version_id)
        self.assertEqual(rollback.image_tag, known_good.image_tag)
        self.assertEqual(rollback.ports, known_good.ports)
        self.assertEqual(rollback.environment, known_good.environment)
        self.assertEqual(rollback.health_url, known_good.health_url)
        self.assertFalse(rollback.auto_heal)
        self.assertEqual(rollback.status, "pending")
        self.assertEqual(result.id, rollback.id)
        enqueue.assert_called_once()
        self.assertEqual(rollback.queue_job_id, "rollback-job-id")

    def test_deployment_state_machine_rejects_invalid_transitions(self):
        deployment_record = Deployment(
            service_id=uuid4(),
            image_tag="onedeploy/service:v1",
            status=DeploymentStatus.PENDING.value,
        )
        with self.assertRaises(ValueError):
            deployment_record.transition_to(DeploymentStatus.RUNNING)

        deployment_record.transition_to(DeploymentStatus.BUILDING)
        deployment_record.transition_to(DeploymentStatus.RUNNING)
        deployment_record.transition_to(DeploymentStatus.ROLLED_BACK)
        self.assertEqual(deployment_record.status, "rolled_back")

    async def test_unavailable_queue_marks_deployment_failed(self):
        queued_deployment = Deployment(
            id=uuid4(),
            service_id=uuid4(),
            image_tag="onedeploy/service:v1",
            status=DeploymentStatus.PENDING.value,
        )
        db = MagicMock()
        db.commit = AsyncMock()

        with patch.object(
            deployment.deployment_queue,
            "enqueue",
            side_effect=deployment.RedisError("Redis unavailable"),
        ):
            with self.assertRaises(HTTPException) as raised:
                await deployment._enqueue_deployment(queued_deployment, db)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(queued_deployment.status, DeploymentStatus.FAILED)
        self.assertIn("Redis unavailable", queued_deployment.error)
        db.commit.assert_awaited_once()

    async def test_deployment_job_endpoint_returns_rq_status(self):
        project_id = uuid4()
        service_id = uuid4()
        deployment_id = uuid4()
        deployment_record = SimpleNamespace(
            id=deployment_id,
            queue_job_id=str(deployment_id),
        )
        query_result = MagicMock()
        query_result.scalar_one_or_none.return_value = deployment_record
        db = MagicMock()
        db.execute = AsyncMock(return_value=query_result)
        job = SimpleNamespace(
            id=str(deployment_id),
            get_status=MagicMock(return_value=SimpleNamespace(value="started")),
        )

        with (
            patch.object(deployment, "_require_service", new=AsyncMock()),
            patch.object(deployment.Job, "fetch", return_value=job) as fetch_job,
        ):
            result = await deployment.get_service_deployment_job(
                project_id,
                service_id,
                deployment_id,
                db,
                SimpleNamespace(id=uuid4()),
            )

        self.assertEqual(result.job_id, str(deployment_id))
        self.assertEqual(result.job_status, "started")
        fetch_job.assert_called_once_with(
            str(deployment_id),
            connection=deployment.redis_connection,
        )
