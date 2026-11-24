import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from git import Repo


def clone_repository(repo_url: str, destination: str):

    if os.path.exists(destination):
        raise ValueError("Destination already exists")

    Repo.clone_from(repo_url, destination)

    return destination


def normalize_github_repository_url(repo_url: str) -> str:
    """Validate a public GitHub HTTPS repository URL and return its canonical URL."""
    parsed = urlsplit(repo_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Only public HTTPS repositories on github.com are supported")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ValueError("Repository URL must include an owner and repository name")

    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", repository
    ):
        raise ValueError("Repository URL contains an invalid owner or repository name")

    return f"https://github.com/{owner}/{repository}.git"


def repository_workspace_path(project_id: str, service_id: str) -> Path:
    """Return the managed checkout path for a project service."""
    return (
        Path(__file__).resolve().parents[1]
        / ".onedeploy"
        / "repositories"
        / project_id
        / service_id
    )


def clone_github_repository(
    repo_url: str,
    project_id: str,
    service_id: str,
) -> tuple[str, Path]:
    """Clone a public GitHub repository into a managed service workspace."""
    normalized_url = normalize_github_repository_url(repo_url)
    destination = repository_workspace_path(project_id, service_id)
    if destination.exists():
        raise FileExistsError("A repository is already cloned for this service")

    destination.parent.mkdir(parents=True, exist_ok=True)
    Repo.clone_from(normalized_url, destination)
    return normalized_url, destination