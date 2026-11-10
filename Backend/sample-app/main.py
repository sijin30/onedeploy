from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def read_root() -> dict[str, str]:
    return {"message": "Welcome to OneDeploy"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
