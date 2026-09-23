import logging
import os
import time

import cachetools
from fastapi import Request
from model import Detector

from app.core.groundlight_client import groundlight_client
from app.escalation_queue.queue_writer import QueueWriter
from app.profiling.context import trace_span

from .database import DatabaseManager
from .edge_inference import EdgeInferenceManager
from .utils import TimestampedCache, safe_call_sdk

logger = logging.getLogger(__name__)

MAX_DETECTOR_IDS_CACHE_SIZE = 1000
STALE_METADATA_THRESHOLD_SEC = 60  # 60 seconds

USE_MINIMAL_IMAGE = os.environ.get("USE_MINIMAL_IMAGE", "false") == "true"
RUN_OODD = os.environ.get("RUN_OODD", "true") == "true"


@trace_span
def refresh_detector_metadata_if_needed(detector_id: str) -> None:
    """Refresh detector metadata from cloud when the cached value is older than the stale threshold."""
    metadata_cache: TimestampedCache = get_detector_metadata.cache
    cached_value_timestamp = metadata_cache.get_timestamp(detector_id)
    if cached_value_timestamp is not None:
        cached_value_age = time.monotonic() - cached_value_timestamp
        if cached_value_age > STALE_METADATA_THRESHOLD_SEC:
            logger.info(f"Detector metadata for {detector_id=} is stale. Attempting to refresh...")
            metadata_cache.suspend_cached_value(detector_id)

            try:
                # Repopulate the cache with fresh metadata
                get_detector_metadata(detector_id=detector_id)
                metadata_cache.delete_suspended_value(detector_id)
                logger.info(f"Detector metadata for {detector_id=} refreshed successfully.")
            except KeyError:
                # This shouldn't happen, but if we fail to delete the suspended value we don't want to try to restore it
                logger.warning(
                    f"After fetching new metadata, did not successfully delete suspended value for {detector_id=}. "
                    "This is unexpected."
                )
            except Exception as e:
                logger.error(
                    f"Failed to refresh detector metadata for {detector_id=}: {e}. Restoring stale cached metadata."
                )
                # The timestamp of the restored value will be updated to the time of restoration. This avoids trying to
                # refresh the metadata again right away, in case the failure was due to a temporary network outage.
                metadata_cache.restore_suspended_value(detector_id)


@trace_span
@cachetools.cached(
    cache=TimestampedCache(maxsize=MAX_DETECTOR_IDS_CACHE_SIZE),
    key=lambda detector_id: detector_id,
)
def get_detector_metadata(detector_id: str) -> Detector:
    """Return detector metadata from the Groundlight API, cached by detector_id."""
    # Short timeouts so a slow or unreachable cloud does not stall metadata lookup
    # (and thus request handling) for long. Values are somewhat arbitrary.
    connect_timeout, read_timeout = 2, 3
    gl = groundlight_client()
    detector = safe_call_sdk(gl.get_detector, id=detector_id, request_timeout=(connect_timeout, read_timeout))
    return detector


class AppState:
    def __init__(self):
        # We only launch a separate OODD inference pod if we are not using the minimal image.
        # Pipelines used in the minimal image include OODD inference and confidence adjustment,
        # so they do not need to be adjusted separately. OODD can also be disabled entirely
        # (regardless of the image) via the RUN_OODD flag.
        self.separate_oodd_inference = (not USE_MINIMAL_IMAGE) and RUN_OODD
        self.edge_inference_manager = EdgeInferenceManager(separate_oodd_inference=self.separate_oodd_inference)
        self.db_manager = DatabaseManager()
        self.is_ready = False
        self.queue_writer = QueueWriter()


@trace_span
async def get_app_state(request: Request) -> AppState:
    """FastAPI dependency that returns the singleton AppState attached to the running app."""
    if not hasattr(request.app.state, "app_state"):
        raise RuntimeError("App state is not initialized.")
    return request.app.state.app_state
