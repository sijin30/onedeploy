import unittest

from services.repository import normalize_github_repository_url


class GitHubRepositoryUrlTests(unittest.TestCase):
    def test_normalizes_repository_url(self):
        self.assertEqual(
            normalize_github_repository_url("https://github.com/owner/repo"),
            "https://github.com/owner/repo.git",
        )
        self.assertEqual(
            normalize_github_repository_url("https://github.com/owner/repo.git"),
            "https://github.com/owner/repo.git",
        )

    def test_rejects_non_github_or_non_https_urls(self):
        invalid_urls = (
            "http://github.com/owner/repo",
            "https://github.com.evil.example/owner/repo",
            "https://user@github.com/owner/repo",
            "https://example.com/owner/repo",
            "https://github.com/owner/repo?redirect=example.com",
        )
        for repository_url in invalid_urls:
            with self.subTest(repository_url=repository_url):
                with self.assertRaises(ValueError):
                    normalize_github_repository_url(repository_url)

    def test_rejects_urls_without_exactly_one_owner_and_repository(self):
        for repository_url in (
            "https://github.com/owner",
            "https://github.com/owner/repo/extra",
        ):
            with self.subTest(repository_url=repository_url):
                with self.assertRaises(ValueError):
                    normalize_github_repository_url(repository_url)


if __name__ == "__main__":
    unittest.main()
