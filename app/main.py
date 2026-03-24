"""The main entrypoint for the inference router.

The inference router handles specific SDK/API requests like submit_image_query
by routing them to an inference_deployment if one is available for the detector.
It is behind nginx, which forwards any request to the cloud if this doesn't handle it.
"""

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.api.api import api_router, edge_config_router, health_router, ping_router
from app.api.naming import API_BASE_PATH
from app.core.app_state import AppState
from app.core.edge_config_loader import load_edge_config, reconcile_config

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DEPLOY_DETECTOR_LEVEL_INFERENCE = bool(int(os.environ.get("DEPLOY_DETECTOR_LEVEL_INFERENCE", 0)))

logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
# The asyncio executor is too verbose at INFO level, so we set it to WARNING
if LOG_LEVEL == "INFO":
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

app = FastAPI(title="edge-endpoint")
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)
app.include_router(router=health_router)
app.include_router(router=edge_config_router)

scheduler = AsyncIOScheduler()


def update_inference_config(app_state: AppState) -> None:
    """Update the App's edge-inference config by querying the database for new detectors."""
    logging.debug("Querying database for updated inference deployment records...")
    detectors = app_state.db_manager.get_inference_deployment_records(
        deployment_created=True, pending_deletion=False
    )
    if detectors:
        for detector_record in detectors:
            app_state.edge_inference_manager.update_inference_config(
                detector_id=detector_record.detector_id,  # type: ignore
                api_token=detector_record.api_token,  # type: ignore
            )
    # TODO: discuss whether per-worker edge_inference_manager (synced from DB every 30s)
    # needs further attention for multi-worker consistency.


@app.on_event("startup")
async def startup_event():
    """Lifecycle event that is triggered when the application starts."""
    logging.info("Starting edge-endpoint application...")
    app.state.app_state = AppState()
    app.state.app_state.db_manager.reset_database()

    config = load_edge_config()
    reconcile_config(config, app.state.app_state.db_manager)
    logging.info(f"edge_config={config}")

    if DEPLOY_DETECTOR_LEVEL_INFERENCE:
        # Add job to periodically update the inference config
        scheduler.add_job(update_inference_config, "interval", seconds=30, args=[app.state.app_state])
        scheduler.start()

    app.state.app_state.is_ready = True
    logging.info("Application is ready to serve requests.")


@app.on_event("shutdown")
async def shutdown_event():
    """Lifecycle event that is triggered when the application is shutting down."""
    app.state.app_state.is_ready = False
    app.state.app_state.db_manager.shutdown()
    if DEPLOY_DETECTOR_LEVEL_INFERENCE:
        scheduler.shutdown()
