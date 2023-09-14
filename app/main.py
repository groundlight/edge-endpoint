import logging
import os

import tritonclient.http as tritonclient
from fastapi import FastAPI

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH
from app.core.edge_inference import INFERENCE_SERVER_URL, update_model

from .core.iqe_cache import IQECache
from .core.motion_detection import MotionDetectionManager, RootConfig
from .core.utils import load_edge_config

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)


app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)


# Create a global shared image query ID cache in the app's state
app.state.iqe_cache = IQECache()

# Create a global shared motion detection manager object in the app's state
edge_config = load_edge_config()
app.state.edge_config = edge_config
app.state.motion_detection_manager = MotionDetectionManager(config=RootConfig(**edge_config))

# Create global shared edge inference client object in the app's state
# NOTE: For now this assumes that there is only one inference container
app.state.inference_client = tritonclient.InferenceServerClient(url=INFERENCE_SERVER_URL)


@app.on_event("startup")
async def on_startup():
    """
    On startup, update edge inference models
    """
    for detector_id in app.state.motion_detection_manager.detectors.keys():
        update_model(app.state.inference_client, detector_id)