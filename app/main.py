import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.api.api import api_router, health_router, ping_router
from app.api.naming import API_BASE_PATH
from app.core.app_state import AppState
from app.db.manager import DatabaseManager, get_database_engine

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DEPLOY_DETECTOR_LEVEL_INFERENCE = bool(int(os.environ.get("DEPLOY_DETECTOR_LEVEL_INFERENCE", 0)))

logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for the FastAPI application.

    This context manager is responsible for initializing and cleaning up
    resources when the application starts and shuts down.

    Args:
        app (FastAPI): The FastAPI application instance.

    On enter (server startup):
        - Initializes the database manager and creates the required tables.
        - Adds a scheduled job to periodically update the inference config.

    Yields (server running):
        None

    On exit (server shutdown):
        - Disposes off the database engine.
        - Shuts down the scheduler.
    """
    engine = get_database_engine()
    db_manager = DatabaseManager(engine)
    app.state.app_state = AppState(db_manager=db_manager)

    # Initialize the database tables
    db_manager = app.state.app_state.db_manager
    db_manager.create_tables()
    logging.info("Database tables created successfully.")

    if DEPLOY_DETECTOR_LEVEL_INFERENCE:
        # Add job to periodically update the inference config
        scheduler.add_job(update_inference_config, "interval", seconds=30, args=[app.state.app_state])
        scheduler.start()
    else:
        logging.info("Detector-level inference is disabled.")

    # Set the application state to ready - /health/ready endpoint will return 200 OK
    logging.info("Application is ready to serve requests.")
    app.state.app_state.is_ready = True

    yield  # Go to the main application

    app.state.app_state.is_ready = False

    engine.dispose()

    if DEPLOY_DETECTOR_LEVEL_INFERENCE:
        scheduler.shutdown()


app = FastAPI(title="edge-endpoint", lifespan=lifespan)
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)
app.include_router(router=health_router)


def update_inference_config(app_state: AppState) -> None:
    """Update the edge inference config by querying the database for new detectors."""
    db_manager: DatabaseManager = app_state.db_manager
    detectors = db_manager.query_inference_deployments(deployment_created=True)
    if detectors:
        for detector_record in detectors:
            detector_id, api_token = detector_record.detector_id, detector_record.api_token
            app_state.edge_inference_manager.update_inference_config(detector_id=detector_id, api_token=api_token)
