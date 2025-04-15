import json
import logging
import os

import psutil
from kubernetes import client, config

logger = logging.getLogger(__name__)


def get_cpu_usage_pct() -> str:
    """Returns the percentage of total CPU used."""
    percent = psutil.cpu_percent(interval=1)
    return percent


def get_memory_used_pct() -> str:
    """Returns the percentage of total memory used."""
    percent = psutil.virtual_memory().percent
    return percent


def get_memory_available_bytes() -> str:
    """Returns the amount of memory available in bytes."""
    total = psutil.virtual_memory().total
    return total


def get_inference_flavor() -> str:
    """Get the inference flavor of the system."""
    inference_flavor = os.getenv("INFERENCE_FLAVOR")
    return inference_flavor


def get_deployments() -> list[str]:
    config.load_incluster_config()
    v1_apps = client.AppsV1Api()

    deployments = v1_apps.list_namespaced_deployment(namespace=os.getenv("NAMESPACE", "edge"))

    deployment_names = []
    for dep in deployments.items:
        deployment_names.append(f"{dep.metadata.namespace}/{dep.metadata.name}")
    return str(deployment_names)


def get_pods() -> list[tuple[str, str]]:
    config.load_incluster_config()
    v1_core = client.CoreV1Api()
    pods = v1_core.list_namespaced_pod(namespace=os.getenv("NAMESPACE", "edge"))

    # Convert the pods dict to a JSON string to prevent opensearch from indexing all
    # the individual pod fields
    return json.dumps({pod.metadata.name: pod.status.phase for pod in pods.items})


def get_container_images() -> list[tuple[str, dict[str, str]]]:
    config.load_incluster_config()
    v1_core = client.CoreV1Api()
    pods = v1_core.list_namespaced_pod(namespace=os.getenv("NAMESPACE", "edge"))

    containers = {}
    for pod in pods.items:
        pod_dict = {}
        for container in pod.status.container_statuses:
            pod_dict[container.name] = container.image_id
        containers[pod.metadata.name] = pod_dict

    # Convert the containers dict to a JSON string to prevent opensearch from indexing all
    # the individual container fields
    return json.dumps(containers)
