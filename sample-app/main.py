from fastapi import FastAPI

app = FastAPI(title="OneDeploy Sample App")


@app.get("/")
async def read_root() -> dict[str, str]:
    return {"message": "Hello from OneDeploy"}