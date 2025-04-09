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


def get_deployments() -> set[str]:
    config.load_incluster_config()
    v1_apps = client.AppsV1Api()

    deployments = v1_apps.list_namespaced_deployment(namespace=os.getenv("NAMESPACE", "edge"))

    deployment_names = []
    for dep in deployments.items:
        deployment_names.append(f"{dep.metadata.namespace}/{dep.metadata.name}")
    return deployment_names


def get_pods() -> dict[str, str]:
    config.load_incluster_config()
    v1_core = client.CoreV1Api()
    pods = v1_core.list_namespaced_pod(namespace=os.getenv("NAMESPACE", "edge"))
    pods_dict = {}
    for pod in pods.items:
        pods_dict[pod.metadata.name] = pod.status.phase
    return pods_dict


def get_container_images() -> dict[str, dict[str, str]]:
    config.load_incluster_config()
    v1_core = client.CoreV1Api()
    pods = v1_core.list_namespaced_pod(namespace=os.getenv("NAMESPACE", "edge"))

    containers_dict = {}
    for pod in pods.items:
        for container in pod.status.container_statuses:
            if pod.metadata.name not in containers_dict:
                containers_dict[pod.metadata.name] = {}
            containers_dict[pod.metadata.name][container.name] = container.image_id
    return containers_dict
