import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict

import psutil
import tzlocal
from kubernetes import client, config

from app.core.edge_inference import (
    get_current_model_version,
    get_current_pipeline_config,
    get_primary_edge_model_dir,
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


def _normalized_detector_id(detector_id: str) -> str:
    """Normalize a detector id to the form used in pod names: replace '_' with '-' and lower-case."""
    return detector_id.replace("_", "-").lower()


def _detector_id_from_primary_pod_name(pod_name: str) -> str | None:
    """Extract the normalized detector id from a primary inference pod name.

    Expected formats (examples):
      - inferencemodel-primary-det-34abcd...-<hash>
    Returns the part between the prefix and the last dash (hash separator).
    """
    prefix = "inferencemodel-primary-"
    if not pod_name.startswith(prefix):
        return None
    rest = pod_name[len(prefix) :]
    # strip trailing -<hash>
    if "-" not in rest:
        return None
    return rest.rsplit("-", 1)[0]


def _map_normalized_to_actual_detector_ids() -> Dict[str, str]:
    """Build a mapping from normalized detector ids to actual detector directory names in the model repo.

    This lets us recover correct casing when we only know the lowercase/normalized id from pod names.
    """
    mapping: Dict[str, str] = {}
    try:
        for entry in os.listdir(MODEL_REPOSITORY_PATH):
            full_path = os.path.join(MODEL_REPOSITORY_PATH, entry)
            if os.path.isdir(full_path):
                mapping[_normalized_detector_id(entry)] = entry
    except Exception as e:
        logger.error(f"Error reading model repository at {MODEL_REPOSITORY_PATH}: {e}")
    return mapping


def get_detector_details() -> dict:
    """Return details for detectors with running primary inference pods.

    Details include:
      - query_text (detector.query from cloud)
      - pipeline_config (the active primary pipeline_config on edge)
    """
    config.load_incluster_config()
    v1_core = client.CoreV1Api()
    namespace = get_namespace()
    pods = v1_core.list_namespaced_pod(namespace=namespace)

    norm_to_actual = _map_normalized_to_actual_detector_ids()

    # Collect normalized detector ids that currently have a running primary pod
    normalized_ids: set[str] = set()
    for pod in pods.items:
        if pod.status.phase != "Running":
            continue
        norm = _detector_id_from_primary_pod_name(pod.metadata.name or "")
        if norm:
            normalized_ids.add(norm)

    # Resolve to actual ids (preserving casing if possible)
    detector_ids: list[str] = []
    for norm in sorted(normalized_ids):
        if norm in norm_to_actual:
            detector_ids.append(norm_to_actual[norm])
        else:
            # Fallback: convert first '-' back to '_' (ids are typically like 'det_xxx')
            detector_ids.append(norm.replace("-", "_", 1))

    details: Dict[str, dict] = {}
    for det_id in detector_ids:
        try:
            # Active primary pipeline_config from model repo
            model_dir = get_primary_edge_model_dir(MODEL_REPOSITORY_PATH, det_id)
            version = get_current_model_version(MODEL_REPOSITORY_PATH, det_id, is_oodd=False)
            pipeline_config = get_current_pipeline_config(model_dir, version) if version is not None else None

            # Query text from predictor_metadata.json in the same model version dir
            query_text = None
            if version is not None:
                predictor_metadata_path = os.path.join(model_dir, str(version), "predictor_metadata.json")
                if os.path.exists(predictor_metadata_path):
                    try:
                        with open(predictor_metadata_path, "r") as f:
                            metadata = json.load(f)
                            # Field is named "text_query" in predictor_metadata
                            query_text = metadata.get("text_query")
                    except Exception as e:
                        logger.error(
                            f"Failed reading predictor_metadata for {det_id} at {predictor_metadata_path}: {e}",
                            exc_info=True,
                        )

            details[det_id] = {
                "query_text": query_text,
                "pipeline_config": pipeline_config,
            }
        except Exception as e:
            logger.error(f"Error collecting detector details for {det_id}: {e}", exc_info=True)
            details[det_id] = {"error": str(e)}

    return details
