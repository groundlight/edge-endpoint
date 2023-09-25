import logging
import os
from functools import lru_cache
from typing import Dict

import cachetools
import yaml
from cachetools import TTLCache
from fastapi import Request
from groundlight import Groundlight
from kubernetes import client as kube_client
from kubernetes import config
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

    logger.warning("EDGE_CONFIG environment variable not set. Checking default locations.")

    default_config_paths = ["/etc/groundlight/edge-config.yaml", "configs/edge-config.yaml"]
    for default_config_path in default_config_paths:
        if os.path.exists(default_config_path):
            logger.info(f"Loading edge config from {default_config_path}")
            config = yaml.safe_load(open(default_config_path, "r"))
            return RootEdgeConfig(**config)

    raise FileNotFoundError(f"Could not find edge config file in default locations: {default_config_paths}")


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
    # TTL cache for k3s health checks on inference deployments. Checks are cached for 10 minutes.
    KUBERNETES_HEALTH_CHECKS_TTL_CACHE = TTLCache(maxsize=MAX_DETECTOR_IDS_TTL_CACHE_SIZE, ttl=600)

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
        self.edge_inference_manager = EdgeInferenceManager(config=inference_config)

        deploy_inference_per_detector = os.environ.get("DEPLOY_INFERENCE_PER_DETECTOR", None)

        if deploy_inference_per_detector:
            self._setup_kube_client()

    def _setup_kube_client(self) -> None:
        """
        Sets up the kubernetes client in order to access resources in the cluster.
        """

        # Requires the application to be running inside kubernetes.
        config.load_incluster_config()

        # Kubernetes resources are split across various API groups based on their functionality.
        # The `AppsV1Api` client manages resources related to workloads, such as Deployments, StatefulSets, etc.
        # The `CoreV1Api` client, on the other hand, handles core cluster resources like Pods, Services, and Namespaces.
        # Using both clients in order to create the deployment and service for the inference container.
        self.app_kube_client = kube_client.AppsV1Api()
        self.core_kube_client = kube_client.CoreV1Api()

        self._edge_deployment_template = self._load_k3s_edge_deployment_manifest()

    def _load_k3s_edge_deployment_manifest(self) -> str:
        """
        Loads the k3s edge deployment manifest template.
        """
        deployment_manifest_path = "/etc/groundlight/inference_deployment.yaml"
        if os.path.exists(deployment_manifest_path):
            with open(deployment_manifest_path, "r") as f:
                manifest = f.read()
                return manifest

        raise FileNotFoundError(f"Could not find k3s edge deployment manifest at {deployment_manifest_path}")

    def _apply_kube_manifest(self, k3s_namespace, manifest) -> None:
        """
        Applies the kubernetes manifest to the kubernetes cluster.
        """
        for document in yaml.safe_load_all(manifest):
            try:
                if document["kind"] == "Service":
                    self.core_kube_client.create_namespaced_service(namespace=k3s_namespace, body=document)
                elif document["kind"] == "Deployment":
                    self.app_kube_client.create_namespaced_deployment(namespace=k3s_namespace, body=document)
                else:
                    raise ValueError(f"Unknown kubernetes manifest kind: {document['kind']}")

            except kube_client.rest.ApiException as e:
                # TODO better handling of this exception.
                # Currently not raising the exception (which from the app's perspective is a 500 error) so that
                # we can continue to serve requests through the cloud API even if a specific inference
                # deployment creation fails.
                logger.warning(f"Failed to create a kubernetes deployment: {e}", exc_info=True)

        logger.debug(f"Successfully applied kubernetes manifest to namespace `{k3s_namespace}`")

    @cachetools.cached(
        cache=KUBERNETES_HEALTH_CHECKS_TTL_CACHE,
        key=lambda self, detector_id, *args, **kwargs: detector_id,
    )
    def inference_deployment_is_ready(
        self, detector_id: str, k3s_namespace: str = "default", create_if_absent: bool = False
    ) -> bool:
        """
        Checks if the detector deployment exists, and if not, creates it.
        Running self.app_kube_client.create_namespaced_deployment() is equivalent to
        running `k3s kubectl apply -f <deployment-manifest-yaml> -n <namespace>`
        to create the deployment.

        :param detector_id: ID of the detector on which to run local edge inference
        :param k3s_namespace: Namespace in which to create the deployment
        :param create_if_absent: Whether to create the deployment if it doesn't exist
        """

        if not self.edge_inference_manager.detector_configured_for_local_inference(detector_id=detector_id):
            logger.debug(f"Detector {detector_id} is not configured for local inference")
            return False

        def get_service_and_deployment_names(detector_id: str) -> str:
            """
            Kubernetes service/deployment names have a strict naming convention.
            They have to be alphanumeric, lower cased, and can only contain dashes.
            We just use `inferencemodel-<detector_id>` as the deployment name and
            `inference-service-<detector_id>` as the service name.
            """
            service_name = f"inference-service-{detector_id.replace('_', '-').lower()}"
            deployment_name = f"inferencemodel-{detector_id.replace('_', '-').lower()}"

            return service_name, deployment_name

        service_name, deployment_name = get_service_and_deployment_names(detector_id=detector_id)

        try:
            deployment = self.app_kube_client.read_namespaced_deployment(name=deployment_name, namespace=k3s_namespace)
            if deployment.status.ready_replicas == deployment.spec.replicas:
                logger.debug(f"Deployment {deployment_name} is ready")

                # Check that the model in the deployment is also ready to server inference requests
                return self.edge_inference_manager.inference_is_available(detector_id=detector_id)

        except kube_client.rest.ApiException:
            logger.debug(f"Deployment {deployment_name} does not currently exist in namespace {k3s_namespace}.")
            if create_if_absent:
                logger.debug(f"Creating deployment {deployment_name} in namespace {k3s_namespace}")
                deployment_manifest = self._edge_deployment_template
                deployment_manifest = deployment_manifest.replace("{{ INFERENCE_SERVICE_NAME }}", service_name)
                deployment_manifest = deployment_manifest.replace("{{ DEPLOYMENT_NAME }}", deployment_name)

                self._apply_kube_manifest(k3s_namespace=k3s_namespace, manifest=deployment_manifest)

        return False


def get_app_state(request: Request) -> AppState:
    return request.app.state.app_state
