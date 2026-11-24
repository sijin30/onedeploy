import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.repository import clone_repository


class RepositoryTests(unittest.TestCase):
    def test_clone_repository_rejects_existing_destination(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "repository"
            destination.mkdir()

            with self.assertRaises(ValueError):
                clone_repository(
                    "https://github.com/owner/repository.git",
                    str(destination),
                )

    @patch("services.repository.Repo.clone_from")
    def test_clone_repository_clones_to_new_destination(self, clone_from):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "repository"

            result = clone_repository(
                "https://github.com/owner/repository.git",
                str(destination),
            )

            self.assertEqual(result, str(destination))
            clone_from.assert_called_once_with(
                "https://github.com/owner/repository.git",
                str(destination),
            )


if __name__ == "__main__":
    unittest.main()