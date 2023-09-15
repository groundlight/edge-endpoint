import time
import logging
import os
from functools import lru_cache
from io import BytesIO
from typing import Callable, Dict

import cachetools
import ksuid
import yaml
from cachetools import TTLCache
from fastapi import HTTPException, Request
from groundlight import Groundlight
from model import Detector
from PIL import Image
from kubernetes import client as kube_client
from kubernetes import config

from .configs import LocalInferenceConfig, MotionDetectionConfig, RootEdgeConfig
from .edge_inference import EdgeInferenceManager
from .iqe_cache import IQECache
from .motion_detection import MotionDetectionManager

logger = logging.getLogger(__name__)

MAX_SDK_INSTANCES_CACHE_SIZE = 1000
MAX_DETECTOR_IDS_TTL_CACHE_SIZE = 1000
TTL_TIME = 3600  # 1 hour


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

        # Load the kubernetes config
        config.load_incluster_config()
        self.kube_client = kube_client.AppsV1Api()

        self._edge_deployment_template = self._load_k3s_edge_deployment_manifest()

    def _load_k3s_edge_deployment_manifest(self) -> str:
        """
        Loads the k3s edge deployment manifest from the file system.
        """
        deployment_manifest_path = "configs/k3s/deployment_template.yaml"
        if os.path.exists(deployment_manifest_path):
            with open(deployment_manifest_path, "r") as f:
                manifest = f.read()
                return manifest

        raise FileNotFoundError(f"Could not find k3s edge deployment manifest at {deployment_manifest_path}")

    def check_or_create_detector_deployment(self, detector_id: str, k3s_namespace: str = "default"):
        """
        Checks if the detector deployment exists, and if not, creates it.
        Running self.kube_client.create_namespaced_deployment() is equivalent to
        running `k3s kubectl apply -f <deployment-manifest-yaml> -n <namespace>`
        to create the deployment.
        """

        def get_deployment_name(detector_id: str) -> str:
            """
            Kubernetes deployment names have a strict naming convention.
            They have to be alphanumeric, lower case, and can only contain dashes.
            We just use `edge-endpoint-<detector_id>` as the deployment name.
            """
            return f"edge-endpoint-{detector_id.replace('_', '-').lower()}"

        deployment_name = get_deployment_name(detector_id=detector_id)

        try:
            self.kube_client.read_namespaced_deployment(name=deployment_name, namespace=k3s_namespace)
            logger.info(f"Deployment {deployment_name} already exists")

        except kube_client.rest.ApiException:
            logger.info(f"Creating deployment {deployment_name}")
            # Timing this out for now to see how long creating a deployment takes
            start = time.monotonic()

            deployment_manifest = self._edge_deployment_template
            deployment_manifest.replace("{{ DETECTOR_ID }}", deployment_name)

            self.kube_client.create_namespaced_deployment(
                namespace=k3s_namespace, body=yaml.safe_load(deployment_manifest)
            )
            end = time.monotonic()

            logger.info(
                f"Created deployment {deployment_name} in namespace {k3s_namespace} in {end - start:.3f} seconds"
            )


def get_app_state(request: Request) -> AppState:
    return request.app.state.app_state
