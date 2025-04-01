import logging

# import os
import psutil

# from kubernetes import client, config

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
    return "none"
    # # Load in-cluster config
    # config.load_incluster_config()

    # # Create the AppsV1 API client
    # v1_apps = client.AppsV1Api()

    # # List deployments in current namespace
    # deployments = v1_apps.list_namespaced_deployment(namespace=os.getenv("NAMESPACE", "edge"))

    # deployment_names = []
    # for dep in deployments.items:
    #     logger.info(f"{dep.metadata.namespace}/{dep.metadata.name}")
    #     deployment_names.append(f"{dep.metadata.namespace}/{dep.metadata.name}")
    # return f"{deployment_names}"
