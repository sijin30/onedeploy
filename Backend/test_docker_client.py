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


if __name__ == "__main__":
    unittest.main()
