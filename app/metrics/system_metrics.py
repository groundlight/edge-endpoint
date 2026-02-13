import json
import logging
import os
from datetime import datetime, timedelta

import psutil
import tzlocal
import yaml
from kubernetes import client, config

from app.core.configs import EdgeInferenceConfig
from app.core.edge_config_loader import get_detector_edge_configs_by_id
from app.core.edge_inference import get_current_pipeline_config, get_predictor_metadata, get_primary_edge_model_dir
from app.core.file_paths import MODEL_REPOSITORY_PATH

logger = logging.getLogger(__name__)


def _edge_config_to_dict(config: EdgeInferenceConfig | None) -> dict | None:
    if config is None:
        return None
    return {
        "enabled": config.enabled,
        "always_return_edge_prediction": config.always_return_edge_prediction,
        "disable_cloud_escalation": config.disable_cloud_escalation,
        "min_time_between_escalations": config.min_time_between_escalations,
    }


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


def _get_template_annotation(deployment: client.V1Deployment, key: str) -> str | None:
    tpl_meta = deployment.spec.template.metadata
    if tpl_meta is None:
        return None
    return (tpl_meta.annotations or {}).get(key)


# Waiting-state reasons that indicate a pod error (as opposed to normal startup)
_POD_ERROR_REASONS = frozenset(
    {
        "CrashLoopBackOff",
        "ImagePullBackOff",
        "ErrImagePull",
        "CreateContainerConfigError",
        "InvalidImageName",
        "RunContainerError",
    }
)


def _get_pod_error_reason(pod: client.V1Pod) -> str | None:
    """Return the first error waiting-reason found on any container in this pod, or None."""
    for cs in pod.status.container_statuses or []:
        if cs.state and cs.state.waiting and cs.state.waiting.reason in _POD_ERROR_REASONS:
            return cs.state.waiting.reason
    return None


def _has_progress_deadline_exceeded(deployment: client.V1Deployment) -> bool:
    for c in deployment.status.conditions or []:
        if c.type == "Progressing" and c.status == "False" and c.reason == "ProgressDeadlineExceeded":
            return True
    return False


def _derive_detector_status(
    deployment: client.V1Deployment,
    pods: list[client.V1Pod],
) -> tuple[str, str | None]:
    """Derive a human-readable status from a deployment and its pods.

    Returns (status, status_detail) where status is one of:
      "ready", "updating", "initializing", "error"
    and status_detail is an optional reason string (used for errors).
    """
    desired = deployment.spec.replicas or 1
    available = deployment.status.available_replicas or 0
    updated = deployment.status.updated_replicas or 0
    total = deployment.status.replicas or 0

    # Check for stuck rollout
    if _has_progress_deadline_exceeded(deployment):
        return "error", "ProgressDeadlineExceeded"

    # Check pod-level errors when nothing is available
    if available == 0:
        for pod in pods:
            reason = _get_pod_error_reason(pod)
            if reason:
                return "error", reason
        return "initializing", None

    # At least one pod is available
    if available >= desired and updated >= desired and total <= desired:
        return "ready", None

    return "updating", None


def _enrich_detector_details(
    det_id: str,
    model_version_str: str | None,
    details: dict,
    ready_pod: client.V1Pod | None = None,
) -> None:
    """Fill in pipeline config and metadata fields from model files on disk.

    The model_version_str can come from either a ready pod's annotation or the
    deployment's pod template annotation -- the on-disk model files are readable
    regardless of pod state. Only last_updated_time requires a ready pod.
    """
    if model_version_str is None:
        logger.error(f"No model-version annotation found for {det_id}.")
        return
    if not model_version_str.isdigit():
        logger.error(f"model-version for {det_id} is not a digit.")
        return

    model_version_int = int(model_version_str)
    model_dir = get_primary_edge_model_dir(MODEL_REPOSITORY_PATH, det_id)
    cfg = get_current_pipeline_config(model_dir, model_version_int)
    if cfg is None:
        logger.error(f"Pipeline config not found for detector {det_id} at version {model_version_int}")
        return

    if isinstance(cfg, (dict, list)):
        pipeline_config_str = yaml.safe_dump(cfg, sort_keys=False)
    else:
        pipeline_config_str = str(cfg)

    metadata = get_predictor_metadata(model_dir, model_version_int)
    if metadata is not None:
        details["query"] = metadata.get("text_query")
        details["mode"] = metadata.get("mode")
        details["detector_name"] = metadata.get("detector_name")
    else:
        logger.warning(f"Detector metadata not found for detector {det_id} at version {model_version_int}")

    details["pipeline_config"] = pipeline_config_str

    if ready_pod is not None:
        started = _get_container_started_at(ready_pod)
        details["last_updated_time"] = started.isoformat() if started else None


def get_detector_details() -> str:
    """Return details for detector deployments, keyed by detector-id annotation.

    Uses deployments to derive status and pods to get detailed metadata from ready instances.
    """
    config.load_incluster_config()
    v1_apps = client.AppsV1Api()
    v1_core = client.CoreV1Api()
    namespace = get_namespace()

    deployments = v1_apps.list_namespaced_deployment(namespace=namespace)
    all_pods = v1_core.list_namespaced_pod(namespace=namespace)

    # Index pods by detector-id for quick lookup (primary pods only)
    pods_by_detector: dict[str, list[client.V1Pod]] = {}
    for pod in all_pods.items:
        det_id = _get_annotation(pod, "groundlight.dev/detector-id")
        if det_id and _get_annotation(pod, "groundlight.dev/model-name") == f"{det_id}/primary":
            pods_by_detector.setdefault(det_id, []).append(pod)

    detector_edge_configs = get_detector_edge_configs_by_id()
    detector_details: dict[str, dict] = {}

    for dep in deployments.items:
        det_id = _get_template_annotation(dep, "groundlight.dev/detector-id")
        if not det_id:
            continue
        if _get_template_annotation(dep, "groundlight.dev/model-name") != f"{det_id}/primary":
            continue

        det_pods = pods_by_detector.get(det_id, [])
        status, status_detail = _derive_detector_status(dep, det_pods)

        details: dict = {"status": status}
        if status_detail:
            details["status_detail"] = status_detail

        # Find a ready pod if one exists (for last_updated_time)
        ready_pod = None
        for pod in det_pods:
            if _pod_is_ready(pod):
                ready_pod = pod
                break

        # Prefer model version from a ready pod; fall back to the deployment template
        model_version_str = None
        if ready_pod is not None:
            model_version_str = _get_annotation(ready_pod, "groundlight.dev/model-version")
        if model_version_str is None:
            model_version_str = _get_template_annotation(dep, "groundlight.dev/model-version")

        _enrich_detector_details(det_id, model_version_str, details, ready_pod)

        edge_inference_config = _edge_config_to_dict(detector_edge_configs.get(det_id))
        if edge_inference_config:
            details["edge_inference_config"] = edge_inference_config

        detector_details[det_id] = details

    # Convert to JSON string to prevent opensearch from indexing all detector details
    return json.dumps(detector_details)
