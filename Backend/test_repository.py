from services.repository import clone_repository

path = clone_repository(
    "https://github.com/tiangolo/fastapi.git",
    "./deployments/fastapi"
)

print("Repository cloned to:", path)