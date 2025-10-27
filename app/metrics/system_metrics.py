import json
import logging
import os
import time
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


def _primary_pod_is_ready(pod: client.V1Pod) -> bool:
    if not pod or not pod.status or pod.status.phase != "Running":
        return False
    try:
        if not any(c.type == "Ready" and c.status == "True" for c in (pod.status.conditions or [])):
            return False
    except Exception:
        return False
    try:
        for cs in (pod.status.container_statuses or []):
            if cs.name == "inference-server" and cs.ready:
                return True
    except Exception:
        return False
    return False


def _get_container_started_at(pod: client.V1Pod) -> datetime | None:
    try:
        for cs in (pod.status.container_statuses or []):
            if cs.name == "inference-server" and cs.state and cs.state.running and cs.state.running.started_at:
                return cs.state.running.started_at
    except Exception:
        return None
    return None


def _get_annotation(pod: client.V1Pod, key: str) -> str | None:
    try:
        return (pod.metadata.annotations or {}).get(key)
    except Exception:
        return None


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

    # Group all primary pods by normalized detector id (include non-ready for 'pending')
    norm_to_pods: Dict[str, list[client.V1Pod]] = {}
    for pod in pods.items:
        norm = _detector_id_from_primary_pod_name(pod.metadata.name or "")
        if not norm:
            continue
        norm_to_pods.setdefault(norm, []).append(pod)

    details: Dict[str, dict] = {}
    for norm, pod_list in sorted(norm_to_pods.items()):
        # Determine detector id from pod annotations if available, else best-effort from norm
        ready_pods = [p for p in pod_list if _primary_pod_is_ready(p)]
        any_pod = ready_pods[0] if ready_pods else pod_list[0]
        det_id = _get_annotation(any_pod, "groundlight.dev/detector-id") or norm.replace("-", "_", 1)
        try:
            # Choose a Ready pod if present, else most recent pod (pending)
            ready_pods = [p for p in pod_list if _primary_pod_is_ready(p)]
            pod = ready_pods[0] if ready_pods else sorted(
                pod_list,
                key=lambda p: (p.metadata.creation_timestamp or datetime.min.replace(tzinfo=None)),
                reverse=True,
            )[0]

            if not _primary_pod_is_ready(pod):
                details[det_id] = {"status": "pending"}
                continue

            # Read annotations written by the deployment logic
            pipeline_config = _get_annotation(pod, "groundlight.dev/pipeline-config")
            last_updated_time = _get_annotation(pod, "groundlight.dev/last-updated-time")

            details[det_id] = {
                "status": "ready",
                "pipeline_config": pipeline_config,
                "last_updated_time": last_updated_time,
            }
        except Exception as e:
            logger.error(f"Error collecting detector details for {det_id}: {e}", exc_info=True)
            details[det_id] = {"error": str(e)}

    return details
