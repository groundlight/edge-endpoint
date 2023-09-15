import logging
import os

import tritonclient.http as tritonclient
from fastapi import FastAPI

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH
from app.core.edge_inference import INFERENCE_SERVER_URL

from .core.iqe_cache import IQECache
from .core.motion_detection import MotionDetectionManager, RootConfig
from .core.utils import load_edge_config
from kubernetes import client, config


# Load the kubernetes config
# The default config file for k3s is /etc/rancher/k3s/k3s.yaml, which is different
# from k8s's default config file location of ~/.kube/config
KUBE_CONFIG_PATH = os.environ.get("KUBE_CONFIG_PATH", "/etc/rancher/k3s/k3s.yaml")

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)

logger = logging.getLogger(__name__)


app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)


# Create a global shared image query ID cache in the app's state
app.state.iqe_cache = IQECache()

# Create a global shared motion detection manager object in the app's state
edge_config = load_edge_config()
app.state.motion_detection_manager = MotionDetectionManager(config=RootConfig(**edge_config))

# Create global shared edge inference client object in the app's state
# NOTE: For now this assumes that there is only one inference container
app.state.inference_client = tritonclient.InferenceServerClient(url=INFERENCE_SERVER_URL)


# Load the kubernetes config
config.load_incluster_config()

# Create an API client 
app.state.kube_client = client.CoreV1Api()


pod_list = app.state.kube_client.list_namespaced_pod(namespace="default")
for pod in pod_list.items:
    logger.info(f"pod = {pod.metadata.name}\n")
    logger.info(f"status = {pod.status}\n")
    logger.info(f"ip = {pod.status.pod_ip}\n")
