import logging

import os
import psutil

from kubernetes import client, config

logger = logging.getLogger(__name__)


def get_cpu_usage():
    """Returns the percentage of total CPU used."""
    percent = psutil.cpu_percent(interval=1)
    return f"{percent}%"


def get_percentage_memory_used():
    """Returns the percentage of total memory used."""
    percent = psutil.virtual_memory().percent
    return f"{percent}%"


def get_memory_available():
    """Returns the amount of memory available in GB."""
    total = psutil.virtual_memory().total
    return f"{total / (1024 ** 3):.2f} GB"


def get_deployments():
    config.load_incluster_config()
    v1_apps = client.AppsV1Api()

    # List deployments in current namespace
    deployments = v1_apps.list_namespaced_deployment(namespace=os.getenv("NAMESPACE", "edge"))

    deployment_names = []
    for dep in deployments.items:
        logger.info(f"{dep.metadata.namespace}/{dep.metadata.name}")
        deployment_names.append(f"{dep.metadata.namespace}/{dep.metadata.name}")
    return f"{deployment_names}"

def get_pods():
    config.load_incluster_config()
    v1_core = client.CoreV1Api()
    pods = v1_core.list_namespaced_pod(namespace=os.getenv("NAMESPACE", "edge"))
    pods_dict = {}
    for pod in pods.items:
        logger.info(f"{pod.metadata.namespace}/{pod.metadata.name}")
        logger.info(f"pod.status.phase: {pod.status.phase}")
        # logger.info(f"pod.status.containerStatuses[].imageId: {pod.status.containerStatuses[0].imageId}")
        pods_dict[pod.metadata.name] = pod.status.phase
    return f"{pods_dict}"