import logging
import os
from io import BytesIO
from typing import Callable

import ksuid
from groundlight import Groundlight
import yaml
from fastapi import HTTPException, Request
from PIL import Image
from functools import lru_cache

logger = logging.getLogger(__name__)

MAX_SDK_INSTANCES_CACHE_SIZE = 1000


def load_edge_config() -> dict:
    """
    Reads the edge config from the EDGE_CONFIG environment variable if it exists.
    If EDGE_CONFIG is not set, reads the default edge config file.
    """
    yaml_config = os.environ.get("EDGE_CONFIG", "").strip()
    if yaml_config:
        return yaml.safe_load(yaml_config)

    logger.warning("EDGE_CONFIG environment variable not set. Using the default edge config file.")

    default_config_path = "configs/edge.yaml"
    if os.path.exists(default_config_path):
        return yaml.safe_load(open(default_config_path, "r"))

    raise FileNotFoundError(f"Could not find edge config file at {default_config_path}")


@lru_cache(maxsize=MAX_SDK_INSTANCES_CACHE_SIZE, key=lambda request: request.headers.get("x-api-token"))
def get_groundlight_sdk_instance(request: Request):
    """
    Returns a Groundlight SDK instance given an API token.
    """
    api_token = request.headers.get("x-api-token")
    return Groundlight(api_token=api_token)


def get_iqe_cache(request: Request):
    return request.app.state.iqe_cache


def get_motion_detection_manager(request: Request):
    return request.app.state.motion_detection_manager


def get_inference_client(request: Request):
    return request.app.state.inference_client


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
