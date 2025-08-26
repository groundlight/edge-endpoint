import logging
import os
import time
from functools import lru_cache

import cachetools
import yaml
from fastapi import Request
from groundlight import Groundlight
from model import Detector

from app.escalation_queue.queue_writer import QueueWriter

from .configs import EdgeInferenceConfig, RootEdgeConfig
from .database import DatabaseManager
from .edge_inference import EdgeInferenceManager
from .file_paths import DEFAULT_EDGE_CONFIG_PATH
from .utils import TimestampedCache, safe_call_sdk

logger = logging.getLogger(__name__)

MAX_SDK_INSTANCES_CACHE_SIZE = 1000
MAX_DETECTOR_IDS_CACHE_SIZE = 1000
STALE_METADATA_THRESHOLD_SEC = 30  # 30 seconds

USE_MINIMAL_IMAGE = os.environ.get("USE_MINIMAL_IMAGE", "false") == "true"


def load_edge_config() -> RootEdgeConfig:
    """
    Reads the edge config from the EDGE_CONFIG environment variable if it exists.
    If EDGE_CONFIG is not set, reads the default edge config file.
    """
    yaml_config = os.environ.get("EDGE_CONFIG", "").strip()
    if yaml_config:
        return _load_config_from_yaml(yaml_config)

    logger.warning("EDGE_CONFIG environment variable not set. Checking default locations.")

    if os.path.exists(DEFAULT_EDGE_CONFIG_PATH):
        logger.info(f"Loading edge config from {DEFAULT_EDGE_CONFIG_PATH}")
        with open(DEFAULT_EDGE_CONFIG_PATH, "r") as f:
            return _load_config_from_yaml(f)

    raise FileNotFoundError(f"Could not find edge config file in default location: {DEFAULT_EDGE_CONFIG_PATH}")


def _load_config_from_yaml(yaml_config) -> RootEdgeConfig:
    """
    Creates a `RootEdgeConfig` from the config yaml. Raises an error if there are duplicate detector ids.
    """
    config = yaml.safe_load(yaml_config)

    detectors = config.get("detectors", [])
    detector_ids = [det["detector_id"] for det in detectors]

    # Check for duplicate detector IDs
    if len(detector_ids) != len(set(detector_ids)):
        raise ValueError("Duplicate detector IDs found in the configuration. Each detector should only have one entry.")

    config["detectors"] = {det["detector_id"]: det for det in detectors}

    return RootEdgeConfig(**config)


def get_detector_inference_configs(
    root_edge_config: RootEdgeConfig,
) -> dict[str, EdgeInferenceConfig] | None:
    """
    Produces a dict mapping detector IDs to their associated `EdgeInferenceConfig`.
    Returns None if there are no detectors in the config file.
    """
    # Mapping of config names to EdgeInferenceConfig objects
    edge_inference_configs: dict[str, EdgeInferenceConfig] = root_edge_config.edge_inference_configs

    # Filter out detectors whose ID's are empty strings
    detectors = {det_id: detector for det_id, detector in root_edge_config.detectors.items() if det_id != ""}

    detector_to_inference_config: dict[str, EdgeInferenceConfig] | None = None
    if detectors:
        detector_to_inference_config = {
            detector_id: edge_inference_configs[detector_config.edge_inference_config]
            for detector_id, detector_config in detectors.items()
        }

    return detector_to_inference_config


@lru_cache(maxsize=MAX_SDK_INSTANCES_CACHE_SIZE)
def _get_groundlight_sdk_instance_internal(api_token: str):
    return Groundlight(api_token=api_token)


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
    detector = safe_call_sdk(gl.get_detector, id=detector_id)
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
