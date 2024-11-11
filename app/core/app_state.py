import logging
import os
from functools import lru_cache
from typing import Any

import cachetools
import yaml
from fastapi import Request
from groundlight import Groundlight
from model import Detector

from .configs import RootEdgeConfig
from .database import DatabaseManager
from .edge_inference import EdgeInferenceManager
from .file_paths import DEFAULT_EDGE_CONFIG_PATH
from .utils import safe_call_sdk

logger = logging.getLogger(__name__)

MAX_SDK_INSTANCES_CACHE_SIZE = 1000
MAX_DETECTOR_IDS_TTL_CACHE_SIZE = 1000
TTL_TIME = 3600  # 1 hour


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
    detectors: list[dict[str, Any]] = config.get(
        "detectors", []
    )  # A list of dicts with info about detectors, if present

    # TODO test the errors that get raised here

    # Build detector mapping and check for duplicates
    detector_mapping = {}
    for detector in detectors:
        det_id = detector.get("detector_id", None)
        if det_id is None:
            raise ValueError("Invalid detector config - you must specify a detector ID.")
        if det_id == "":
            continue  # Skip if the detector ID is an empty string

        if det_id in detector_mapping:
            raise ValueError(
                f"Duplicate detector ID '{det_id}' found in the configuration. "
                "Each detector should only have one entry."
            )
        detector_mapping[det_id] = detector

    config["detectors"] = detector_mapping
    return RootEdgeConfig(**config)


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


@cachetools.cached(
    cache=cachetools.TTLCache(maxsize=MAX_DETECTOR_IDS_TTL_CACHE_SIZE, ttl=TTL_TIME),
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
        self.edge_inference_manager = EdgeInferenceManager(edge_config=self.edge_config)
        self.db_manager = DatabaseManager()
        self.is_ready = False


def get_app_state(request: Request) -> AppState:
    if not hasattr(request.app.state, "app_state"):
        raise RuntimeError("App state is not initialized.")
    return request.app.state.app_state
