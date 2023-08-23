from io import BytesIO
from typing import Callable
import os
import yaml
import base64

import ksuid
from fastapi import HTTPException, Request
from PIL import Image


def load_edge_config() -> dict | None:
    """
    Reads the edge config from the EDGE_CONFIG environment variable if it exists.
    If EDGE_CONFIG is not set, reads the default edge config file.
    """
    encoded_yaml_block = os.environ.get("EDGE_CONFIG", None)
    if encoded_yaml_block is not None:
        decoded_yaml_block = base64.b64decode(encoded_yaml_block).decode("utf-8")
        config = yaml.safe_load(decoded_yaml_block)
        return config

    default_config_path = "configs/edge.yaml"
    if os.path.exists(default_config_path):
        return yaml.safe_load(open(default_config_path, "r"))

    return None


def get_groundlight_sdk_instance(request: Request):
    return request.app.state.groundlight


def get_motion_detector_instance(request: Request):
    return request.app.state.motion_detector


def get_edge_detector_manager(request: Request):
    return request.app.state.edge_detector_manager


def get_motion_detection_manager(request: Request):
    return request.app.state.motion_detection_manager


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
