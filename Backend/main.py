from fastapi import FastAPI

from Routers.auth import router as auth_router
from Routers.health import router as health_router


app = FastAPI(title="OneDeploy")


app.include_router(health_router)
app.include_router(auth_router)