import logging
import os
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from pyinstrument import Profiler
from pyinstrument.renderers.html import HTMLRenderer
from pyinstrument.renderers.speedscope import SpeedscopeRenderer

from app.api.api import api_router, health_router, ping_router
from app.api.naming import API_BASE_PATH
from app.core.app_state import AppState

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
DEPLOY_DETECTOR_LEVEL_INFERENCE = bool(int(os.environ.get("DEPLOY_DETECTOR_LEVEL_INFERENCE", 0)))

logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)


app = FastAPI(title="edge-endpoint")
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)
app.include_router(router=health_router)

scheduler = AsyncIOScheduler()

PROFILING_ENABLED = True

if PROFILING_ENABLED:

    @app.middleware("http")
    async def profile_request(request: Request, call_next: Callable):
        """Profile the current request

        Taken from https://pyinstrument.readthedocs.io/en/latest/guide.html#profile-a-web-request-in-fastapi
        with small improvements.

        """
        # we map a profile type to a file extension, as well as a pyinstrument profile renderer
        profile_type_to_ext = {"html": "html", "speedscope": "speedscope.json"}
        profile_type_to_renderer = {
            "html": HTMLRenderer,
            "speedscope": SpeedscopeRenderer,
        }

        urls_to_profile = [
            "/device-api/v1/image-queries",
            "/device-api/v1/image-queries?detector_id=det_2mIZTxUnJDhhUtJbUXavUevW15K",
        ]

        # if the `profile=true` HTTP query argument is passed, we profile the request
        if request.url.path in urls_to_profile and request.query_params.get("profile", True):
            logging.info(f"Profiling the request with url: {request.url.path}")
            # The default profile format is speedscope
            # profile_type = request.query_params.get("profile_format", "speedscope")
            profile_type = "speedscope"

            # we profile the request along with all additional middlewares, by interrupting
            # the program every 1ms1 and records the entire stack at that point
            with Profiler(interval=0.001, async_mode="enabled") as profiler:
                response = await call_next(request)

            # we dump the profiling into a file
            extension = profile_type_to_ext[profile_type]
            renderer = profile_type_to_renderer[profile_type]()
            with open(f"profile.{extension}", "w") as out:
                out.write(profiler.output(renderer=renderer))
                logging.info(f"Wrote to profile.{extension} inside {os.getcwd()}")
            return response

        # Proceed without profiling
        return await call_next(request)


def update_inference_config(app_state: AppState) -> None:
    """Update the App's edge-inference config by querying the database for new detectors."""
    detectors = app_state.db_manager.get_inference_deployment_records(deployment_created=True)
    if detectors:
        for detector_record in detectors:
            app_state.edge_inference_manager.update_inference_config(
                detector_id=detector_record.detector_id,  # type: ignore
                api_token=detector_record.api_token,  # type: ignore
            )


@app.on_event("startup")
async def startup_event():
    """Lifecycle event that is triggered when the application starts."""
    app.state.app_state = AppState()
    app.state.app_state.db_manager.reset_database()

    if DEPLOY_DETECTOR_LEVEL_INFERENCE:
        # Add job to periodically update the inference config
        scheduler.add_job(update_inference_config, "interval", seconds=30, args=[app.state.app_state])
        scheduler.start()

    app.state.app_state.is_ready = True
    logging.info("Application is ready to server requests.")


@app.on_event("shutdown")
async def shutdown_event():
    """Lifecycle event that is triggered when the application is shutting down."""
    app.state.app_state.is_ready = False
    app.state.app_state.db_manager.shutdown()
    if DEPLOY_DETECTOR_LEVEL_INFERENCE:
        scheduler.shutdown()
