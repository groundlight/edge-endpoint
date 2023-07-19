from fastapi import FastAPI
from groundlight import Groundlight

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH

from .core.motion_detection import AsyncMotionDetector, MotdetParameterSettings

app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)


# Create global shared Groundlight SDK client object in the app's state
app.state.groundlight = Groundlight()

# Create global shared motion detector object in the app's state
app.state.motion_detector = AsyncMotionDetector(parameters=MotdetParameterSettings())
