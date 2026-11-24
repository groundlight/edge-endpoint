import logging
import os
import threading
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

_metadata_refresh_lock = threading.Lock()


@trace_span
def refresh_detector_metadata_if_needed(detector_id: str) -> None:
    """Refresh detector metadata from cloud when the cached value is older than the stale threshold.

    The cached value keeps being served while the refresh is in flight and is only replaced if the fetch succeeds.
    """
    metadata_cache: TimestampedCache = get_detector_metadata.cache
    with _metadata_refresh_lock:
        cached_value_timestamp = metadata_cache.get_timestamp(detector_id)
        if cached_value_timestamp is None:
            return
        if time.monotonic() - cached_value_timestamp <= STALE_METADATA_THRESHOLD_SEC:
            return
        # Re-stamping before the fetch claims this refresh, so concurrent callers in this process skip it instead of
        # each calling the cloud. If the fetch fails, it also delays the next attempt by a full stale interval.
        metadata_cache.touch(detector_id)

    logger.info(f"Detector metadata for {detector_id=} is stale. Attempting to refresh...")
    try:
        detector = _fetch_detector_metadata(detector_id)
    except Exception as e:
        logger.error(f"Failed to refresh detector metadata for {detector_id=}: {e}. Keeping stale cached metadata.")
        return
    metadata_cache[detector_id] = detector
    logger.info(f"Detector metadata for {detector_id=} refreshed successfully.")


@trace_span
def _fetch_detector_metadata(detector_id: str) -> Detector:
    """Fetch detector metadata from the Groundlight API, bypassing the cache."""
    # Short timeouts so a slow or unreachable cloud does not stall metadata lookup
    # (and thus request handling) for long. Values are somewhat arbitrary.
    connect_timeout, read_timeout = 2, 3
    gl = groundlight_client()
    return safe_call_sdk(gl.get_detector, id=detector_id, request_timeout=(connect_timeout, read_timeout))


@trace_span
@cachetools.cached(
    cache=TimestampedCache(maxsize=MAX_DETECTOR_IDS_CACHE_SIZE),
    key=lambda detector_id: detector_id,
)
def get_detector_metadata(detector_id: str) -> Detector:
    """Return detector metadata from the Groundlight API, cached by detector_id."""
    return _fetch_detector_metadata(detector_id)


class AppState:
    def __init__(self):
        # We only launch a separate OODD inference pod if we are not using the minimal image.
        # Pipelines used in the minimal image include OODD inference and confidence adjustment,
        # so they do not need to be adjusted separately.
        self.separate_oodd_inference = not USE_MINIMAL_IMAGE
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
