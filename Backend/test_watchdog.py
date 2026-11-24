import unittest
from unittest.mock import MagicMock, patch

from services import watchdog


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        watchdog._failed_checks.clear()
        watchdog._restart_attempts.clear()

    def test_assess_container_rejects_crashed_status(self):
        container = MagicMock()
        container.status = "exited"
        container.labels = {}

        healthy, detection = watchdog.assess_container(container)

        self.assertFalse(healthy)
        self.assertIn("exited", detection)

    def test_assess_container_honors_auto_heal_exclusion(self):
        container = MagicMock()
        container.status = "running"
        container.labels = {
            watchdog.HEALTH_EXCLUDED_LABEL: "false",
        }

        healthy, detection = watchdog.assess_container(container)

        self.assertTrue(healthy)
        self.assertIn("excluded", detection)

    @patch("services.watchdog.docker_client.get_docker_container_stats")
    def test_assess_container_detects_high_memory_usage(self, get_stats):
        get_stats.return_value = {
            "cpu_percent": 10.0,
            "memory_percent": 90.0,
        }
        container = MagicMock()
        container.status = "running"
        container.labels = {}

        with patch.object(
            watchdog.settings,
            "WATCHDOG_MEMORY_PERCENT_THRESHOLD",
            85,
        ):
            healthy, detection = watchdog.assess_container(container)

        self.assertFalse(healthy)
        self.assertIn("Memory usage", detection)

    @patch("services.watchdog.check_http_health", return_value=False)
    def test_assess_container_detects_failed_health_endpoint(
        self, check_health
    ):
        container = MagicMock()
        container.status = "running"
        container.labels = {
            watchdog.HEALTH_URL_LABEL: "http://localhost:8000/health",
        }

        healthy, detection = watchdog.assess_container(container)

        self.assertFalse(healthy)
        check_health.assert_called_once_with(
            "http://localhost:8000/health"
        )
        self.assertIn("Health endpoint failed", detection)

    def test_http_health_accepts_success_status(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response

        with patch("services.watchdog.urllib.request.urlopen", return_value=response):
            self.assertTrue(
                watchdog.check_http_health("http://localhost:8000/health")
            )


if __name__ == "__main__":
    unittest.main()
