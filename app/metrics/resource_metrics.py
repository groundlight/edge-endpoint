"""Collects per-detector GPU and RAM usage for the status page.

GPU (VRAM) data comes from each inference pod's /gpu-usage HTTP endpoint.
RAM data comes from the Kubernetes Metrics Server (metrics.k8s.io/v1beta1).
System-level RAM uses the Kubernetes Node API so that the numbers match
the kubelet's view of memory (which drives eviction decisions).
"""

import json
import logging
import re

import requests
from kubernetes import client, config

from app.metrics.system_metrics import _pod_is_ready, get_namespace

logger = logging.getLogger(__name__)

GPU_ENDPOINT_PORT = 8000
GPU_ENDPOINT_PATH = "/gpu-usage"
HTTP_TIMEOUT_SEC = 2

_K8S_MEM_SUFFIXES = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
}
_K8S_MEM_RE = re.compile(r"^(\d+)([A-Za-z]{1,2})?$")


def _parse_k8s_memory(quantity: str) -> int:
    """Parse a Kubernetes memory quantity string (e.g. '524288Ki') into bytes."""
    m = _K8S_MEM_RE.match(quantity)
    if not m:
        return 0
    value = int(m.group(1))
    suffix = m.group(2)
    if suffix:
        return value * _K8S_MEM_SUFFIXES.get(suffix, 1)
    return value


class ResourceMetricsCollector:
    """Collects GPU and RAM usage per inference pod."""

    def collect(self) -> dict:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            logger.warning("Not running in cluster, cannot collect resource metrics")
            return {"error": "Not running in a Kubernetes cluster"}

        namespace = get_namespace()
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(namespace=namespace)

        inference_pods = _find_inference_pods(pods)
        if not inference_pods:
            return _empty_response()

        active_pods = _pick_active_pods(inference_pods)
        ram_by_pod = _get_pod_ram_metrics(namespace)

        detectors: dict[str, dict] = {}
        loading_vram_bytes = 0
        loading_ram_bytes = 0
        all_gpus_total = 0
        all_gpus_used = 0
        observed_gpus: dict[str, dict] = {}

        for pod, det_id, is_oodd, _is_ready in inference_pods:
            gpu_data = _query_pod_gpu(pod)

            if gpu_data is not None:
                gpu_devices = gpu_data.get("gpus") or []
                pod_total = 0
                pod_used = 0
                for device in gpu_devices:
                    gpu_name = device.get("name")
                    gpu_total = device.get("total_bytes", 0)
                    gpu_used = device.get("used_bytes", 0)
                    gpu_uuid = device.get("uuid")
                    gpu_index = device.get("index")
                    pod_total += gpu_total
                    pod_used += gpu_used
                    if not gpu_name:
                        continue
                    key = str(gpu_uuid or f"{gpu_name}:{gpu_index}")
                    existing = observed_gpus.get(key)
                    if existing is None or gpu_total > existing.get("total_vram_bytes", 0):
                        observed_gpus[key] = {
                            "name": gpu_name,
                            "total_vram_bytes": gpu_total,
                            "used_vram_bytes": gpu_used,
                            "index": gpu_index,
                        }
                    elif gpu_used > existing.get("used_vram_bytes", 0):
                        existing["used_vram_bytes"] = gpu_used

                all_gpus_total = max(all_gpus_total, pod_total)
                all_gpus_used = max(all_gpus_used, pod_used)

            pod_info = (gpu_data.get("pod") or {}) if gpu_data else {}
            process_vram = pod_info.get("vram_bytes") or 0
            process_ram = ram_by_pod.get(pod.metadata.name, 0)

            if pod.metadata.name not in active_pods:
                loading_vram_bytes += process_vram
                loading_ram_bytes += process_ram
                continue

            if det_id not in detectors:
                detectors[det_id] = {
                    "detector_id": det_id,
                    "primary_vram_bytes": None,
                    "oodd_vram_bytes": None,
                    "total_vram_bytes": 0,
                    "primary_ram_bytes": None,
                    "oodd_ram_bytes": None,
                    "total_ram_bytes": 0,
                }
            det = detectors[det_id]
            if is_oodd:
                det["oodd_vram_bytes"] = (det["oodd_vram_bytes"] or 0) + process_vram
                det["oodd_ram_bytes"] = (det["oodd_ram_bytes"] or 0) + process_ram
            else:
                det["primary_vram_bytes"] = (det["primary_vram_bytes"] or 0) + process_vram
                det["primary_ram_bytes"] = (det["primary_ram_bytes"] or 0) + process_ram
            det["total_vram_bytes"] = (det["primary_vram_bytes"] or 0) + (det["oodd_vram_bytes"] or 0)
            det["total_ram_bytes"] = (det["primary_ram_bytes"] or 0) + (det["oodd_ram_bytes"] or 0)

        node_ram = _get_node_ram()

        return {
            "total_vram_bytes": all_gpus_total,
            "used_vram_bytes": all_gpus_used,
            "total_ram_bytes": node_ram["total"],
            "used_ram_bytes": node_ram["used"],
            "ram_eviction_threshold_pct": node_ram["eviction_threshold_pct"],
            "detectors": list(detectors.values()),
            "loading_vram_bytes": loading_vram_bytes,
            "loading_ram_bytes": loading_ram_bytes,
            "observed_gpus": sorted(
                observed_gpus.values(),
                key=lambda g: (
                    g.get("index") if isinstance(g.get("index"), int) else 1_000_000,
                    g.get("name") or "",
                ),
            ),
        }


def _empty_response() -> dict:
    node_ram = _get_node_ram()
    return {
        "total_vram_bytes": 0,
        "used_vram_bytes": 0,
        "total_ram_bytes": node_ram["total"],
        "used_ram_bytes": node_ram["used"],
        "ram_eviction_threshold_pct": node_ram["eviction_threshold_pct"],
        "detectors": [],
        "loading_vram_bytes": 0,
        "loading_ram_bytes": 0,
        "observed_gpus": [],
    }


def _get_node_ram() -> dict:
    """Get system RAM total and used from the Kubernetes Node API and Metrics Server.

    Uses the node's capacity for total RAM and the Metrics Server for current
    usage. This matches the kubelet's view of memory, which drives pod eviction.
    Also extracts the kubelet's soft eviction threshold so the frontend can
    display it on the donut chart.
    """
    try:
        v1 = client.CoreV1Api()
        nodes = v1.list_node()
        if not nodes.items:
            raise ValueError("No nodes found")
        node = nodes.items[0]
        total = _parse_k8s_memory(node.status.capacity.get("memory", "0"))

        custom = client.CustomObjectsApi()
        node_metrics = custom.list_cluster_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            plural="nodes",
        )
        used = 0
        for item in node_metrics.get("items", []):
            if item.get("metadata", {}).get("name") == node.metadata.name:
                used = _parse_k8s_memory(item.get("usage", {}).get("memory", "0"))
                break

        eviction_pct = _parse_eviction_threshold(node)

        return {"total": total, "used": used, "eviction_threshold_pct": eviction_pct}
    except Exception:
        logger.error("Failed to get node RAM from Kubernetes APIs", exc_info=True)
        return {"total": 0, "used": 0, "eviction_threshold_pct": None}


_EVICTION_MEM_RE = re.compile(r"memory\.available<(\d+)%")


def _parse_eviction_threshold(node) -> int | None:
    """Extract the soft memory eviction threshold from kubelet args.

    Returns the percentage of total RAM at which the kubelet starts evicting
    pods (i.e. 100 - available%), or None if not found. Checks the
    k3s.io/node-args annotation for eviction-soft first, then eviction-hard.
    """
    annotations = node.metadata.annotations or {}
    node_args_raw = annotations.get("k3s.io/node-args", "")
    try:
        args = json.loads(node_args_raw) if node_args_raw else []
    except (json.JSONDecodeError, TypeError):
        return None

    for flag in ("eviction-soft=", "eviction-hard="):
        for arg in args:
            if flag in str(arg):
                m = _EVICTION_MEM_RE.search(str(arg))
                if m:
                    available_pct = int(m.group(1))
                    return 100 - available_pct
    return None


def _find_inference_pods(pod_list) -> list[tuple]:
    """Return (pod, detector_id, is_oodd, is_ready) for running inference pods."""
    results = []
    for pod in pod_list.items:
        if not pod.status or pod.status.phase != "Running":
            continue
        if not pod.status.pod_ip:
            continue
        annotations = pod.metadata.annotations or {}
        det_id = annotations.get("groundlight.dev/detector-id")
        model_name = annotations.get("groundlight.dev/model-name")
        if not det_id or not model_name:
            continue
        is_oodd = model_name.endswith("/oodd")
        is_ready = _pod_is_ready(pod)
        results.append((pod, det_id, is_oodd, is_ready))
    return results


def _pick_active_pods(pods: list[tuple]) -> set[str]:
    """Return pod names that should be attributed to their detector.

    For each (detector_id, is_oodd) group, the newest ready pod is "active".
    If no pod in the group is ready, none are active (all go to loading).
    Every other pod's resources will be counted as "loading".
    """
    groups: dict[tuple[str, bool], list[tuple]] = {}
    for entry in pods:
        _, det_id, is_oodd, _ = entry
        groups.setdefault((det_id, is_oodd), []).append(entry)

    active: set[str] = set()
    for group in groups.values():
        ready = [e for e in group if e[3]]
        if ready:
            best = max(ready, key=lambda e: e[0].metadata.creation_timestamp or "")
            active.add(best[0].metadata.name)
    return active


def _query_pod_gpu(pod) -> dict | None:
    """HTTP GET /gpu-usage on a single inference pod. Returns parsed JSON or None."""
    url = f"http://{pod.status.pod_ip}:{GPU_ENDPOINT_PORT}{GPU_ENDPOINT_PATH}"
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT_SEC)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.debug(f"Failed to query GPU usage from pod {pod.metadata.name} at {url}")
        return None


def _get_pod_ram_metrics(namespace: str) -> dict[str, int]:
    """Query the Kubernetes Metrics Server for per-pod RAM usage.

    Returns {pod_name: total_ram_bytes}. Returns an empty dict if the
    Metrics Server is unavailable.
    """
    try:
        custom = client.CustomObjectsApi()
        result = custom.list_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="pods",
        )
    except Exception:
        logger.debug("Metrics Server unavailable, skipping RAM metrics")
        return {}

    ram_by_pod: dict[str, int] = {}
    for item in result.get("items", []):
        pod_name = item.get("metadata", {}).get("name", "")
        total = 0
        for container in item.get("containers", []):
            usage = container.get("usage", {})
            total += _parse_k8s_memory(usage.get("memory", "0"))
        ram_by_pod[pod_name] = total
    return ram_by_pod
