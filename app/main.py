from fastapi import FastAPI

from app.api.api import api_router, ping_router

API_VERSION = "v1"
API_PREFIX = "/device-api"
API_BASE_PATH = f"{API_PREFIX}/{API_VERSION}"

app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)
