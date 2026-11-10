import os
from git import Repo


def clone_repository(repo_url: str, destination: str):

    if os.path.exists(destination):
        raise ValueError("Destination already exists")

    Repo.clone_from(repo_url, destination)

    return destination