import logging
import os
from typing import Dict, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH

from .core.app_state import AppState

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DEPLOY_DETECTOR_LEVEL_INFERENCE = bool(int(os.environ.get("DEPLOY_DETECTOR_LEVEL_INFERENCE", 0)))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)

app.state.app_state = AppState()
scheduler = AsyncIOScheduler()


def update_inference_config(app_state: AppState) -> None:
    """
    Update the edge inference config by querying the database for new detectors.

    :param app_state: Application's state manager.
    :type app_state: AppState
    :return: None
    :rtype: None
    """

    db_manager = app_state.db_manager
    detectors: List[Dict[str, str]] = db_manager.query_inference_deployments(deployment_created=True)
    if detectors:
        for detector_record in detectors:
            detector_id, api_token = detector_record.detector_id, detector_record.api_token
            app_state.edge_inference_manager.update_inference_config(detector_id=detector_id, api_token=api_token)


@app.on_event("startup")
async def startup_event():
    # Initialize the database tables
    db_manager = app.state.app_state.db_manager
    db_manager.create_tables()

    if DEPLOY_DETECTOR_LEVEL_INFERENCE:
        # Add job to periodically update the inference config
        scheduler.add_job(update_inference_config, "interval", seconds=30, args=[app.state.app_state])

        # Start the scheduler
        scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    # Dispose off the database engine
    app.state.app_state.db_manager.shutdown()

    if DEPLOY_DETECTOR_LEVEL_INFERENCE:
        scheduler.shutdown()
