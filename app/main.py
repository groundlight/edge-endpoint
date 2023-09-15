import logging
import os

from fastapi import FastAPI

from app.api.api import api_router, ping_router
from app.api.naming import API_BASE_PATH

from .core.utils import AppState

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)

logger = logging.getLogger(__name__)


app = FastAPI()
app.include_router(router=api_router, prefix=API_BASE_PATH)
app.include_router(router=ping_router)

app.state.app_state = AppState()


# Load the kubernetes config
config.load_incluster_config()

# Create an API client
app.state.kube_client = kube_client.CoreV1Api()


pod_list = app.state.kube_client.list_namespaced_pod(namespace="default")
for pod in pod_list.items:
    logger.info(f"pod = {pod.metadata.name}\n")
    logger.info(f"status = {pod.status}\n")
    logger.info(f"ip = {pod.status.pod_ip}\n")
