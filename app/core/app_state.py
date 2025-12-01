import logging
import os
import time
from functools import lru_cache

import cachetools
from fastapi import Request
from groundlight import Groundlight
from model import Detector
from urllib3.util.retry import Retry

from app.escalation_queue.queue_writer import QueueWriter

from .configs import EdgeInferenceConfig
from .database import DatabaseManager
from .edge_inference import EdgeInferenceManager
from .edge_config_loader import get_detector_inference_configs, load_edge_config
from .utils import TimestampedCache, safe_call_sdk

logger = logging.getLogger(__name__)

MAX_SDK_INSTANCES_CACHE_SIZE = 1000
MAX_DETECTOR_IDS_CACHE_SIZE = 1000
STALE_METADATA_THRESHOLD_SEC = 60  # 60 seconds

USE_MINIMAL_IMAGE = os.environ.get("USE_MINIMAL_IMAGE", "false") == "true"


@lru_cache(maxsize=MAX_SDK_INSTANCES_CACHE_SIZE)
def _get_groundlight_sdk_instance_internal(api_token: str):
    # We set the HTTP transport retries to 0 to avoid stalling too long when experiencing network connectivity issues.
    # By default, urllib3 retries are only done for idempotent methods (which does not include POST). This configuration
    # therefore will not affect submission of image queries.
    http_transport_retries = Retry(total=0)
    return Groundlight(api_token=api_token, http_transport_retries=http_transport_retries)


def get_groundlight_sdk_instance(request: Request):
    """
    Returns a (cached) Groundlight SDK instance given an API token.
    The SDK handles validation of the API token token itself, so there's no
    need to do that here.
    """
    api_token = request.headers.get("x-api-token")
    return _get_groundlight_sdk_instance_internal(api_token)


def refresh_detector_metadata_if_needed(detector_id: str, gl: Groundlight) -> None:
    """
    Check if detector metadata needs refreshing based on age of cached value and refresh it if it's too old.
    If the refresh fails, the stale cached metadata is restored.
    """
    metadata_cache: TimestampedCache = get_detector_metadata.cache
    cached_value_timestamp = metadata_cache.get_timestamp(detector_id)
    if cached_value_timestamp is not None:
        cached_value_age = time.monotonic() - cached_value_timestamp
        if cached_value_age > STALE_METADATA_THRESHOLD_SEC:
            logger.info(f"Detector metadata for {detector_id=} is stale. Attempting to refresh...")
            metadata_cache.suspend_cached_value(detector_id)

            try:
                # Repopulate the cache with fresh metadata
                get_detector_metadata(detector_id=detector_id, gl=gl)
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


@cachetools.cached(
    cache=TimestampedCache(maxsize=MAX_DETECTOR_IDS_CACHE_SIZE),
    key=lambda detector_id, gl: detector_id,
)
def get_detector_metadata(detector_id: str, gl: Groundlight) -> Detector:
    """
    Returns detector metadata from the Groundlight API.
    Caches the result so that we don't have to make an expensive API call every time.
    """
    # We set a lower connect and read timeout to avoid stalling too long when experiencing network connectivity issues.
    # These values are somewhat arbitrarily set and can be adjusted in conjunction with the http_transport_retries
    # parameter for the Groundlight instance to achieve a different balance of robustness vs speed.
    connect_timeout, read_timeout = 2, 3
    detector = safe_call_sdk(gl.get_detector, id=detector_id, request_timeout=(connect_timeout, read_timeout))
    return detector


class AppState:
    def __init__(self):
        self.edge_config = load_edge_config()
        # We only launch a separate OODD inference pod if we are not using the minimal image.
        # Pipelines used in the minimal image include OODD inference and confidence adjustment,
        # so they do not need to be adjusted separately.
        self.separate_oodd_inference = not USE_MINIMAL_IMAGE
        detector_inference_configs = get_detector_inference_configs(root_edge_config=self.edge_config)
        self.edge_inference_manager = EdgeInferenceManager(
            detector_inference_configs=detector_inference_configs, separate_oodd_inference=self.separate_oodd_inference
        )
        self.db_manager = DatabaseManager()
        self.is_ready = False
        self.queue_writer = QueueWriter()


def get_app_state(request: Request) -> AppState:
    if not hasattr(request.app.state, "app_state"):
        raise RuntimeError("App state is not initialized.")
    return request.app.state.app_state
