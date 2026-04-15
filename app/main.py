"""The main entrypoint for the inference router.

The inference router handles specific SDK/API requests like submit_image_query
by routing them to an inference_deployment if one is available for the detector.
It is behind nginx, which forwards any request to the cloud if this doesn't handle it.
"""

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from groundlight.edge import EdgeEndpointConfig

from app.api.api import api_router, edge_config_router, edge_detector_readiness_router, health_router, ping_router
from app.api.naming import API_BASE_PATH
from app.core.app_state import AppState
from app.core.edge_config_manager import EdgeConfigManager, reconcile_config
from app.core.file_paths import ACTIVE_EDGE_CONFIG_PATH, HELM_CONFIGMAP_PATH
from app.profiling import PROFILING_ENABLED
from app.profiling.middleware import ProfilingMiddleware

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

app = FastAPI(title="edge-endpoint")
if PROFILING_ENABLED:
    app.add_middleware(ProfilingMiddleware)
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
    # Ensure backwards compatibility. When we are confident that all users have upgraded, we can deprecate this logic.
    elif not os.path.exists(ACTIVE_EDGE_CONFIG_PATH):
        if os.path.exists(HELM_CONFIGMAP_PATH):
            logging.warning(
                "Active config file not found at %s, but Helm ConfigMap exists at %s. "
                "This likely means the Helm chart version does not yet support SDK-based config management. "
                "Copying Helm ConfigMap to active config for backward compatibility.",
                ACTIVE_EDGE_CONFIG_PATH,
                HELM_CONFIGMAP_PATH,
            )
            EdgeConfigManager.save(EdgeEndpointConfig.from_yaml(filename=HELM_CONFIGMAP_PATH))
        else:
            logging.warning("No active config file or Helm ConfigMap found. Using Pydantic defaults.")

    if PROFILING_ENABLED:
        from app.profiling import get_profiling_manager

        logging.info("Profiling is enabled. Trace data will be written to disk.")
        scheduler = AsyncIOScheduler()
        scheduler.add_job(get_profiling_manager().cleanup_old_files, "interval", hours=1)
        scheduler.start()
        app.state.profiling_scheduler = scheduler

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
    if hasattr(app.state, "profiling_scheduler"):
        app.state.profiling_scheduler.shutdown()
