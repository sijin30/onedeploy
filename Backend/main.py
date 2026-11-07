from fastapi import FastAPI

from Routers.auth import router as auth_router
from Routers.health import router as health_router
from Routers.project import router as project_router
from Routers.service import router as service_router
app = FastAPI(title="OneDeploy")


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(project_router)
app.include_router(service_router)