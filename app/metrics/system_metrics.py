import json
import logging
import os
from datetime import datetime, timedelta

import psutil
import tzlocal
from kubernetes import client, config

logger = logging.getLogger(__name__)


def get_cpu_utilization() -> str:
    """Returns the percentage of total CPU used."""
    percent = psutil.cpu_percent(interval=1)
    return percent


def get_memory_utilization() -> str:
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


def get_namespace() -> str:
    """
    Get the namespace of the EE.

    Use the NAMESPACE environment variable if it exists (helm setup method), otherwise use the
    DEPLOYMENT_NAMESPACE environment variable (setup-ee.sh method). If neither exist, default to
    the namespace "edge"
    """
    namespace = os.getenv("NAMESPACE", os.getenv("DEPLOYMENT_NAMESPACE"))

    if namespace is None:
        logger.error("Neither NAMESPACE nor DEPLOYMENT_NAMESPACE are set, using default namespace 'edge'")
        namespace = "edge"

    return namespace


def get_deployments() -> str:
    config.load_incluster_config()
    v1_apps = client.AppsV1Api()

    namespace = get_namespace()
    deployments = v1_apps.list_namespaced_deployment(namespace=namespace)

    deployment_names = []
    for dep in deployments.items:
        deployment_names.append(f"{dep.metadata.namespace}/{dep.metadata.name}")
    return str(deployment_names)


def get_pods() -> str:
    config.load_incluster_config()
    v1_core = client.CoreV1Api()
    namespace = get_namespace()
    pods = v1_core.list_namespaced_pod(namespace=namespace)

    filtered_pods = [pod for pod in pods.items if should_record_pod(pod)]

    # Convert the pods dict to a JSON string to prevent opensearch from indexing all
    # the individual pod fields
    return json.dumps({pod.metadata.name: pod.status.phase for pod in filtered_pods})


def should_record_pod(pod: client.V1Pod) -> bool:
    """Returns True if the pod should be recorded, False otherwise.

    If the pod has failed, we only record it if it failed within the last hour. This is to prevent us from getting too
    long of a log message to be properly parsed. If we're missing the information in the pod status to determine when it
    failed, we record it.
    """
    if pod.status.phase != "Failed":
        return True
    elif len(pod.status.conditions) == 0:
        logger.warning(
            f"Pod {pod.metadata.name} has no conditions, recording it in system metrics. {pod.status.conditions}"
        )
        return True

    last_transition_times = [condition.last_transition_time for condition in pod.status.conditions]
    if None in last_transition_times:
        logger.warning(
            f"Pod {pod.metadata.name} has a condition with no last transition time, recording it in system metrics. {pod.status.conditions}"
        )
        return True

    return max(last_transition_times) > datetime.now(tzlocal.get_localzone()) - timedelta(hours=1)


def get_container_images() -> str:
    config.load_incluster_config()
    v1_core = client.CoreV1Api()
    namespace = get_namespace()
    pods = v1_core.list_namespaced_pod(namespace=namespace)

    containers = {}
    for pod in pods.items:
        pod_dict = {}
        for container in pod.status.container_statuses:
            pod_dict[container.name] = container.image_id
        containers[pod.metadata.name] = pod_dict

    # Convert the containers dict to a JSON string to prevent opensearch from indexing all
    # the individual container fields
    return json.dumps(containers)
