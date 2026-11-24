from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import docker

from services import docker_client


class DockerClientTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()

    @patch("services.docker_client.docker.from_env")
    def test_create_docker_client_uses_environment_configuration(
        self, from_env
    ):
        from_env.return_value = self.client

        result = docker_client.create_docker_client()

        self.assertIs(result, self.client)
        from_env.assert_called_once_with()

    def test_get_docker_info_returns_engine_info_and_closes_client(self):
        expected_info = {"ServerVersion": "test-version"}
        self.client.info.return_value = expected_info

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.get_docker_info()

        self.assertIs(result, expected_info)
        self.client.info.assert_called_once_with()
        self.client.close.assert_called_once_with()

    def test_get_docker_info_closes_client_on_error(self):
        self.client.info.side_effect = docker.errors.DockerException(
            "Engine unavailable"
        )

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            with self.assertRaises(docker.errors.DockerException):
                docker_client.get_docker_info()

        self.client.close.assert_called_once_with()

    def test_list_docker_images_returns_images_and_closes_client(self):
        expected_images = [MagicMock()]
        self.client.images.list.return_value = expected_images

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.list_docker_images()

        self.assertIs(result, expected_images)
        self.client.images.list.assert_called_once_with()
        self.client.close.assert_called_once_with()

    def test_list_docker_images_closes_client_on_error(self):
        self.client.images.list.side_effect = docker.errors.DockerException(
            "Engine unavailable"
        )

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            with self.assertRaises(docker.errors.DockerException):
                docker_client.list_docker_images()

        self.client.close.assert_called_once_with()

    def test_list_running_containers_returns_containers_and_closes_client(self):
        expected_containers = [MagicMock()]
        self.client.containers.list.return_value = expected_containers

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.list_running_containers()

        self.assertIs(result, expected_containers)
        self.client.containers.list.assert_called_once_with()
        self.client.close.assert_called_once_with()

    def test_list_running_containers_closes_client_on_error(self):
        self.client.containers.list.side_effect = docker.errors.DockerException(
            "Engine unavailable"
        )

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            with self.assertRaises(docker.errors.DockerException):
                docker_client.list_running_containers()

        self.client.close.assert_called_once_with()

    def test_build_docker_image_builds_with_tag_and_labels(self):
        image = MagicMock()
        self.client.images.build.return_value = (image, iter(()))
        labels = {"com.onedeploy.project": "project-id"}

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.build_docker_image(
                Path("repository"), "onedeploy/test:latest", labels
            )

        self.assertIs(result, image)
        self.client.images.build.assert_called_once_with(
            path=str(Path("repository")),
            tag="onedeploy/test:latest",
            rm=True,
            labels=labels,
        )
        self.client.close.assert_called_once_with()

    def test_tag_docker_image_adds_tag_and_closes_client(self):
        image = self.client.images.get.return_value
        image.tag.return_value = True

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            docker_client.tag_docker_image(
                "sha256:image", "onedeploy/service", "latest"
            )

        self.client.images.get.assert_called_once_with("sha256:image")
        image.tag.assert_called_once_with("onedeploy/service", tag="latest")
        self.client.close.assert_called_once_with()

    def test_tag_docker_image_raises_when_docker_rejects_tag(self):
        image = self.client.images.get.return_value
        image.tag.return_value = False

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            with self.assertRaises(docker.errors.DockerException):
                docker_client.tag_docker_image(
                    "sha256:image", "onedeploy/service", "latest"
                )

        self.client.close.assert_called_once_with()

    def test_run_docker_container_starts_detached_container(self):
        container = self.client.containers.run.return_value
        labels = {"com.onedeploy.service": "service-id"}
        ports = {"8000/tcp": 8000}
        environment = {"MODE": "test"}

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.run_docker_container(
                "onedeploy/test:latest",
                "onedeploy-test",
                labels,
                ports,
                environment,
            )

        self.assertIs(result, container)
        self.client.containers.run.assert_called_once_with(
            "onedeploy/test:latest",
            name="onedeploy-test",
            detach=True,
            labels=labels,
            ports=ports,
            environment=environment,
        )
        container.reload.assert_called_once_with()
        self.client.close.assert_called_once_with()

    def test_list_service_containers_filters_by_labels(self):
        expected_containers = [MagicMock()]
        self.client.containers.list.return_value = expected_containers
        labels = {
            "com.onedeploy.project": "project-id",
            "com.onedeploy.service": "service-id",
        }

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.list_service_containers(labels)

        self.assertIs(result, expected_containers)
        self.client.containers.list.assert_called_once_with(
            all=True,
            filters={
                "label": [
                    "com.onedeploy.project=project-id",
                    "com.onedeploy.service=service-id",
                ]
            },
        )
        self.client.close.assert_called_once_with()

    def test_get_docker_container_reload_and_close(self):
        container = self.client.containers.get.return_value

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.get_docker_container("container-id")

        self.assertIs(result, container)
        self.client.containers.get.assert_called_once_with("container-id")
        container.reload.assert_called_once_with()
        self.client.close.assert_called_once_with()

    def test_manage_docker_container_applies_lifecycle_action(self):
        container = self.client.containers.get.return_value

        for action in ("start", "stop", "restart"):
            with self.subTest(action=action):
                self.client.reset_mock()
                container.reset_mock()

                with patch.object(
                    docker_client,
                    "create_docker_client",
                    return_value=self.client,
                ):
                    result = docker_client.manage_docker_container(
                        "container-id", action
                    )

                self.assertIs(result, container)
                getattr(container, action).assert_called_once_with()
                container.reload.assert_called_once_with()
                self.client.close.assert_called_once_with()

    def test_manage_docker_container_removes_container(self):
        container = self.client.containers.get.return_value

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.manage_docker_container(
                "container-id", "remove"
            )

        self.assertIsNone(result)
        container.remove.assert_called_once_with()
        self.client.close.assert_called_once_with()

    def test_get_docker_container_logs_decodes_text(self):
        container = self.client.containers.get.return_value
        container.logs.return_value = b"hello\n"

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.get_docker_container_logs("container-id")

        self.assertEqual(result, "hello\n")
        container.logs.assert_called_once_with()
        self.client.close.assert_called_once_with()

    def test_get_docker_container_stats_calculates_usage(self):
        container = self.client.containers.get.return_value
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 500, "percpu_usage": [1, 1]},
                "system_cpu_usage": 1000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 400},
                "system_cpu_usage": 800,
            },
            "memory_stats": {"usage": 500, "limit": 1000},
        }

        with patch.object(
            docker_client, "create_docker_client", return_value=self.client
        ):
            result = docker_client.get_docker_container_stats("container-id")

        self.assertEqual(
            result,
            {"cpu_percent": 100.0, "memory_percent": 50.0},
        )
        container.stats.assert_called_once_with(stream=False)
        self.client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
