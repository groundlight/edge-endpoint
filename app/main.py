import logging
import os

from fastapi import FastAPI

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH

from .core.utils import AppState

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DEPLOY_INFERENCE_PER_DETECTOR = os.environ.get("DEPLOY_INFERENCE_PER_DETECTOR", "True").lower() == "true"

logging.basicConfig(level=LOG_LEVEL)


app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)

app.state.app_state = AppState()
