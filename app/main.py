"""The main entrypoint for the inference router.

The inference router handles specific SDK/API requests like submit_image_query
by routing them to an inference_deployment if one is available for the detector.
It is behind nginx, which forwards any request to the cloud if this doesn't handle it.
"""

import logging
import os

from fastapi import FastAPI

from groundlight.edge import EdgeEndpointConfig

from app.api.api import api_router, edge_config_router, edge_detector_readiness_router, health_router, ping_router
from app.api.naming import API_BASE_PATH
from app.core.app_state import AppState
from app.core.edge_config_manager import EdgeConfigManager, reconcile_config

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

app = FastAPI(title="edge-endpoint")
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)
app.include_router(router=health_router)
app.include_router(router=edge_config_router)
app.include_router(router=edge_detector_readiness_router)


@app.on_event("startup")
async def startup_event():
    """Lifecycle event that is triggered when the application starts."""
    logging.info("Starting edge-endpoint application...")
    app.state.app_state = AppState()
    app.state.app_state.db_manager.reset_database()

    env_config = os.environ.get("EDGE_CONFIG", "").strip()
    if env_config:
        logging.info("EDGE_CONFIG env var set, writing to active config file")
        EdgeConfigManager.save(EdgeEndpointConfig.from_yaml(yaml_str=env_config))

    config = EdgeConfigManager.active()
    reconcile_config(config, app.state.app_state.db_manager)
    logging.info(f"edge_config={config}")

    app.state.app_state.is_ready = True
    logging.info("Application is ready to serve requests.")


@app.on_event("shutdown")
async def shutdown_event():
    """Lifecycle event that is triggered when the application is shutting down."""
    app.state.app_state.is_ready = False
    app.state.app_state.db_manager.shutdown()
