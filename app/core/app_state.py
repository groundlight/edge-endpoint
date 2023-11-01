import logging
import os
from functools import lru_cache
from typing import Dict

import cachetools
import yaml
from fastapi import Request
from groundlight import Groundlight
from model import Detector
from typing import Tuple

from .configs import LocalInferenceConfig, MotionDetectionConfig, RootEdgeConfig
from .database import DatabaseManager
from .edge_inference import EdgeInferenceManager
from .file_paths import DEFAULT_EDGE_CONFIG_PATH
from .motion_detection import MotionDetectionManager
from .utils import safe_call_api

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
        config = yaml.safe_load(yaml_config)
        return RootEdgeConfig(**config)

    logger.warning("EDGE_CONFIG environment variable not set. Checking default locations.")

    if os.path.exists(DEFAULT_EDGE_CONFIG_PATH):
        logger.info(f"Loading edge config from {DEFAULT_EDGE_CONFIG_PATH}")
        with open(DEFAULT_EDGE_CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
        return RootEdgeConfig(**config)

    raise FileNotFoundError(f"Could not find edge config file in default location: {DEFAULT_EDGE_CONFIG_PATH}")


def get_inference_and_motion_detection_configs(
    root_edge_config: RootEdgeConfig,
) -> Tuple[Dict[str, LocalInferenceConfig], Dict[str, MotionDetectionConfig]]:
    motion_detection_templates: Dict[str, MotionDetectionConfig] = root_edge_config.motion_detection_templates
    edge_inference_templates: Dict[str, LocalInferenceConfig] = root_edge_config.local_inference_templates

    # Filter out detectors whose ID's are empty strings
    detectors = list(filter(lambda detector: detector.detector_id != "", root_edge_config.detectors))

    motion_detection_config = None
    inference_config = None
    if detectors:
        motion_detection_config: Dict[str, MotionDetectionConfig] = {
            detector.detector_id: motion_detection_templates[detector.motion_detection_template]
            for detector in detectors
        }
        inference_config: Dict[str, LocalInferenceConfig] = {
            detector.detector_id: edge_inference_templates[detector.local_inference_template] for detector in detectors
        }

    return inference_config, motion_detection_config


@lru_cache(maxsize=MAX_SDK_INSTANCES_CACHE_SIZE)
def _get_groundlight_sdk_instance_internal(api_token: str):
    return Groundlight(api_token=api_token)


def get_groundlight_sdk_instance(request: Request):
    """
    Returns a Groundlight SDK instance given an API token.
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
    detector = safe_call_api(gl.get_detector, id=detector_id)
    return detector


class AppState:
    def __init__(self):
        self.edge_config = load_edge_config()
        inference_config, motion_detection_config = get_inference_and_motion_detection_configs(
            root_edge_config=self.edge_config
        )

        self.motion_detection_manager = MotionDetectionManager(config=motion_detection_config)
        self.edge_inference_manager = EdgeInferenceManager(config=inference_config)
        self.db_manager = DatabaseManager()


def get_app_state(request: Request) -> AppState:
    return request.app.state.app_state
