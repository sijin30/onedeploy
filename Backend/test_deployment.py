import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import docker
from fastapi import HTTPException

from Routers import deployment
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

    async def test_container_creation_records_requested_image_version(self):
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
        container = MagicMock()
        container.id = "container-id"
        container.name = "service-container"
        container.status = "running"
        container.attrs = {
            "Image": "sha256:image-four",
            "Config": {"Image": image_version.image_tag},
            "Created": "2026-11-24T00:00:00Z",
            "NetworkSettings": {"Ports": {}},
        }

        with (
            patch.object(deployment, "_require_service", new=AsyncMock()),
            patch.object(
                deployment,
                "run_in_threadpool",
                new=AsyncMock(return_value=container),
            ) as run_in_threadpool,
        ):
            result = await deployment.create_service_container(
                project_id,
                service_id,
                DockerContainerCreate(image_version=4),
                db,
                current_user,
            )

        history = db.add.call_args.args[0]
        self.assertEqual(history.image_version_id, image_version.id)
        self.assertEqual(history.image_tag, image_version.image_tag)
        self.assertEqual(history.image_id, container.attrs["Image"])
        self.assertEqual(history.container_id, container.id)
        self.assertEqual(history.status, "running")
        self.assertEqual(result.id, container.id)
        self.assertEqual(
            run_in_threadpool.await_args.args[1],
            image_version.image_tag,
        )

    async def test_default_container_creation_uses_latest_immutable_version(self):
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
        container = MagicMock()
        container.id = "container-id"
        container.name = "service-container"
        container.status = "running"
        container.attrs = {
            "Image": image_version.image_id,
            "Config": {"Image": image_version.image_tag},
            "Created": "2026-11-24T00:00:00Z",
            "NetworkSettings": {"Ports": {}},
        }

        with (
            patch.object(deployment, "_require_service", new=AsyncMock()),
            patch.object(
                deployment,
                "run_in_threadpool",
                new=AsyncMock(return_value=container),
            ) as run_in_threadpool,
        ):
            await deployment.create_service_container(
                project_id,
                service_id,
                DockerContainerCreate(),
                db,
                SimpleNamespace(id=uuid4()),
            )

        self.assertEqual(
            run_in_threadpool.await_args.args[1],
            image_version.image_tag,
        )

    async def test_failed_container_creation_is_recorded(self):
        project_id = uuid4()
        service_id = uuid4()
        image_version = SimpleNamespace(
            id=uuid4(),
            image_tag=f"onedeploy/{project_id.hex}-{service_id.hex}:v2",
            image_id="sha256:image-two",
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
                deployment,
                "run_in_threadpool",
                new=AsyncMock(
                    side_effect=docker.errors.ImageNotFound("missing image")
                ),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await deployment.create_service_container(
                    project_id,
                    service_id,
                    DockerContainerCreate(image_version=2),
                    db,
                    current_user,
                )

        self.assertEqual(raised.exception.status_code, 409)
        history = db.add.call_args.args[0]
        self.assertEqual(history.status, "failed")
        self.assertIn("missing image", history.error)
