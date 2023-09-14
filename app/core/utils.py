import logging
import os
from functools import lru_cache
from io import BytesIO
from typing import Callable, Dict
import cachetools
from cachetools import TTLCache
import ksuid
import yaml
from fastapi import HTTPException, Request
from groundlight import Groundlight
from PIL import Image

from .configs import LocalInferenceConfig, MotionDetectionConfig, RootEdgeConfig
from .edge_inference import EdgeInferenceManager
from .iqe_cache import IQECache
from .motion_detection import MotionDetectionManager

logger = logging.getLogger(__name__)

MAX_SDK_INSTANCES_CACHE_SIZE = 1000
MAX_DETECTOR_IDS_TTL_CACHE_SIZE = 1000
TTL_TIME = 3600  # 1 hour

# Define a TTL (time-to-live) cache for detector IDs.
# This is used to ensure that we don't make too many requests to the Groundlight API
# while trying to only get the confidence threshold for a detector.
ttl_cache = TTLCache(maxsize=MAX_DETECTOR_IDS_TTL_CACHE_SIZE, ttl=TTL_TIME)


def safe_call_api(api_method: Callable, **kwargs):
    """
    This ensures that we correctly handle HTTP error status codes. In some cases,
    for instance, 400 error codes from the SDK are forwarded as 500 by FastAPI,
    which is not what we want.
    """
    try:
        return api_method(**kwargs)

    except Exception as e:
        if hasattr(e, "status"):
            raise HTTPException(status_code=e.status, detail=str(e))
        raise e


def prefixed_ksuid(prefix: str = None) -> str:
    """Returns a unique identifier, with a bunch of nice properties.
    It's statistically guaranteed unique, about as strongly as UUIDv4 are.
    They're sortable by time, approximately, assuming your clocks are sync'd properly.
    They are a single text token, without any hyphens, so you can double-click to select them
    and not worry about your log-search engine (ElasticSearch etc) tokenizing them into parts.
    They can include a semantic prefix such as "chk_" to help identify them.
    They're base62 encoded, so no funny characters, but denser than hex coding of UUID.

    This is just a prefixed KSUID, which is cool.
    """
    if prefix:
        if not prefix.endswith("_"):
            prefix = f"{prefix}_"
    else:
        prefix = ""
    # the "ms" version adds millisecond-level time resolution, at the cost of a equivalent bits of random.
    # Actual collisions remain vanishingly unlikely, and the database would block them if they did happen.
    # But having millisecond resolution is useful in that it means multiple IDs generated during
    # the same request will get ordered properly.
    k = ksuid.KsuidMs()
    out = f"{prefix}{k}"
    return out


def pil_image_to_bytes(img: Image.Image, format: str = "JPEG") -> bytes:
    """
    Convert a PIL Image object to JPEG bytes.

    Args:
        img (Image.Image): The PIL Image object.
        format (str, optional): The image format. Defaults to "JPEG".

    Returns:
        bytes: The raw bytes of the image.
    """
    with BytesIO() as buffer:
        img.save(buffer, format=format)
        return buffer.getvalue()


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


@cachetools.cached(cache=ttl_cache)
def get_detector_confidence(detector_id: str, gl: Groundlight):
    """
    Returns the confidence threshold for a detector.
    """
    detector = gl.get_detector(detector_id=detector_id)
    return detector.confidence_threshold


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
