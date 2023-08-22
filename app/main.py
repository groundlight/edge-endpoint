import logging
import os
import yaml
import base64
from fastapi import FastAPI
from groundlight import Groundlight

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH

from .core.edge_detector_manager import EdgeDetectorManager
from .core.motion_detection import RootConfig, MotionDetectionManager

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
encoded_yaml_block = os.environ.get("EDGE_CONFIG", None)

logging.basicConfig(level=LOG_LEVEL)

decoded_yaml_block = base64.b64decode(encoded_yaml_block).decode("utf-8")
config = yaml.safe_load(decoded_yaml_block)


app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)


# Create a global shared Groundlight SDK client object in the app's state
app.state.groundlight = Groundlight()


# Create a global shared edge detector manager object in the app's state
app.state.edge_detector_manager = EdgeDetectorManager()

# Create a global shared motion detection manager object in the app's state
app.state.motion_detection_manager = MotionDetectionManager(config=RootConfig(**config))
