import logging
import os
from functools import lru_cache
from typing import Dict

import cachetools
import yaml
from cachetools import TTLCache
from fastapi import Request
from groundlight import Groundlight
from model import Detector

from app.core.utils import safe_call_api

from .configs import LocalInferenceConfig, MotionDetectionConfig, RootEdgeConfig
from .edge_inference import EdgeInferenceManager
from .iqe_cache import IQECache
from .motion_detection import MotionDetectionManager

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

    logger.warning("EDGE_CONFIG environment variable not set. Using the default edge config file.")

    default_config_path = "configs/edge-config.yaml"
    if os.path.exists(default_config_path):
        config = yaml.safe_load(open(default_config_path, "r"))
        return RootEdgeConfig(**config)

    raise FileNotFoundError(f"Could not find edge config file at {default_config_path}")


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
    cache=TTLCache(maxsize=MAX_DETECTOR_IDS_TTL_CACHE_SIZE, ttl=TTL_TIME), key=lambda detector_id, gl: detector_id
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
        # Create a global shared image query ID cache in the app's state
        self.iqe_cache = IQECache()

        edge_config = load_edge_config()
        motion_detection_templates: Dict[str, MotionDetectionConfig] = edge_config.motion_detection_templates
        edge_inference_templates: Dict[str, LocalInferenceConfig] = edge_config.local_inference_templates

        motion_detection_config: Dict[str, MotionDetectionConfig] = {
            detector.detector_id: motion_detection_templates[detector.motion_detection_template]
            for detector in edge_config.detectors
        }
        inference_config: Dict[str, LocalInferenceConfig] = {
            detector.detector_id: edge_inference_templates[detector.local_inference_template]
            for detector in edge_config.detectors
        }

        # Create a global shared motion detection manager object in the app's state
        self.motion_detection_manager = MotionDetectionManager(config=motion_detection_config)

        # Create global shared edge inference manager object in the app's state
        # NOTE: For now this assumes that there is only one inference container
        self.edge_inference_manager = EdgeInferenceManager(config=inference_config)


def get_app_state(request: Request) -> AppState:
    return request.app.state.app_state
