import logging
import os

from fastapi import FastAPI

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH

from .core.utils import AppState

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)


app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)


app.state.app_state = AppState()


@app.on_event("startup")
async def on_startup():
    """
    On startup, update edge inference models.
    """
    for detector_id, inference_config in app.state.app_state.edge_inference_manager.inference_config.items():
        if inference_config.enabled:
            app.state.app_state.edge_inference_manager.update_model(detector_id)
