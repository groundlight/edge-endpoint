import os

from dotenv import load_dotenv
from fastapi import FastAPI
from groundlight import Groundlight
from pydantic import BaseSettings

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH

from .core.motion_detection import AsyncMotionDetector


class MotdetParameterSettings(BaseSettings):
    """
    Motion detection parameters read from environment variables
    """

    motdet_percentage_threshold: float
    motdet_val_threshold: int

    class Config:
        env_file = ".env"


motdet_settings = MotdetParameterSettings()

app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)


# Create global state for Groundlight and Motion Detection
app.state.groundlight = Groundlight()
app.state.motion_detector = AsyncMotionDetector(
    percentage_threshold=motdet_settings.motdet_percentage_threshold, val_threshold=motdet_settings.motdet_val_threshold
)
