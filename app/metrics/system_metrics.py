import json
import logging
import os
from datetime import datetime, timedelta

import psutil
import tzlocal
import yaml
from kubernetes import client, config

from app.core.edge_inference import (
    EDGE_INFERENCE_CONFIG_FIELDS,
    get_current_pipeline_config,
    get_predictor_metadata,
    get_primary_edge_model_dir,
    load_edge_inference_config,
)
from app.core.file_paths import MODEL_REPOSITORY_PATH

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


def _pod_is_ready(pod: client.V1Pod) -> bool:
    if not pod or not pod.status or pod.status.phase != "Running":
        return False

    if not any(c.type == "Ready" and c.status == "True" for c in (pod.status.conditions or [])):
        return False

    for cs in pod.status.container_statuses or []:
        if cs.name == "inference-server" and cs.ready:
            return True

    return False


def _get_container_started_at(pod: client.V1Pod) -> datetime | None:
    for cs in pod.status.container_statuses or []:
        if cs.name == "inference-server" and cs.state and cs.state.running and cs.state.running.started_at:
            return cs.state.running.started_at

    return None


def _get_annotation(pod: client.V1Pod, key: str) -> str | None:
    return (pod.metadata.annotations or {}).get(key)


def get_detector_details() -> str:
    """Return details for detectors with primary inference pods, keyed by detector-id annotation.

    Only counts pods whose model-name annotation equals "<detector_id>/primary".
    """
    config.load_incluster_config()
    v1_core = client.CoreV1Api()
    namespace = get_namespace()
    pods = v1_core.list_namespaced_pod(namespace=namespace)

    detector_details: dict[str, dict] = {}
    for pod in pods.items:
        det_id = _get_annotation(pod, "groundlight.dev/detector-id")
        if not det_id:
            continue

        # Skip OODD pods; we only want primary inference pods here
        if _get_annotation(pod, "groundlight.dev/model-name") != f"{det_id}/primary":
            continue

        if _pod_is_ready(pod):
            started = _get_container_started_at(pod)

            model_version = _get_annotation(pod, "groundlight.dev/model-version")
            if model_version is None:
                logger.error(f"No model-version annotation found for {det_id}.")
                continue
            elif not model_version.isdigit():
                logger.error(f"model-version for {det_id} is not a digit.")
                continue

            model_version_int = int(model_version)
            model_dir = get_primary_edge_model_dir(MODEL_REPOSITORY_PATH, det_id)
            cfg = get_current_pipeline_config(model_dir, model_version_int)
            if cfg is None:
                logger.error(f"Pipeline config not found for detector {det_id} at version {model_version_int}")
                continue

            # Convert the pipeline config dict to a yaml string
            if isinstance(cfg, (dict, list)):
                pipeline_config_str = yaml.safe_dump(cfg, sort_keys=False)
            else:
                pipeline_config_str = str(cfg)  # This avoids the yaml end of document marker (...)

            # Get the detector metadata
            metadata = get_predictor_metadata(model_dir, model_version_int)
            if metadata is None:
                logger.warning(f"Predictor metadata not found for detector {det_id} at version {model_version_int}")
            detector_query = metadata.get("text_query")
            detector_mode = metadata.get("mode")

            detector_details[det_id] = {
                "pipeline_config": pipeline_config_str,
                "last_updated_time": started.isoformat() if started else None,
                "query": detector_query,
                "mode": detector_mode,
            }

            edge_inference_config = load_edge_inference_config(MODEL_REPOSITORY_PATH, det_id)
            if edge_inference_config is None:
                logger.warning(f"Edge inference config not found for detector {det_id}.")
            else:
                detector_details[det_id]["edge_inference_config"] = edge_inference_config
        else:
            pass  # We won't report any detector details until the detector has a ready pod

    # Convert the dict to a JSON string to prevent opensearch from indexing all detector details
    return json.dumps(detector_details)
