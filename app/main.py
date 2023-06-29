import os
from fastapi import FastAPI
from groundlight import Groundlight
from dotenv import load_dotenv

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH


from .core.motion_detection import AsyncMotionDetector

app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)

# Read motion detection environment variables
load_dotenv()

percentage_threshold = float(os.getenv("MOTDET_PERCENTAGE_THRESHOLD"))
val_threshold = float(os.getenv("MOTDET_VAL_THRESHOLD"))

# Create global state for Groundlight and Motion Detection
app.state.groundlight = Groundlight()
app.state.motion_detector = AsyncMotionDetector(percentage_threshold=percentage_threshold, val_threshold=val_threshold)
