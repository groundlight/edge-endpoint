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
    """Collects GPU and RAM usage per inference pod.

    The emitted payload is grouped by resource type (`ram` / `vram`) at both the
    system level and per-detector, so every resource has a consistent shape
    (`used_bytes`, `total_bytes`, ...) and new resources can be added without
    reshuffling top-level keys.
    """

    def collect(self) -> dict:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            logger.warning("Not running in cluster, cannot collect resource metrics")
            return {"error": "Not running in a Kubernetes cluster"}

        namespace = get_namespace()
        v1 = client.CoreV1Api()
        inference_pods = _find_inference_pods(v1.list_namespaced_pod(namespace=namespace))
        node_ram = _get_node_ram()

        if inference_pods:
            active_pods = _pick_active_pods(inference_pods)
            ram_by_pod = _get_pod_ram_metrics(namespace)
            gpu_responses = _query_all_pod_gpus(inference_pods)
            observed_gpus, total_vram, used_vram = _build_gpu_summary(gpu_responses)
            detectors, loading_vram, loading_ram = _attribute_detector_resources(
                inference_pods, active_pods, gpu_responses, ram_by_pod
            )
        else:
            observed_gpus, total_vram, used_vram = [], 0, 0
            detectors, loading_vram, loading_ram = [], 0, 0

        return {
            "system": {
                "ram": {
                    "used_bytes": node_ram["used"],
                    "total_bytes": node_ram["total"],
                    "loading_detectors_bytes": loading_ram,
                    "eviction_threshold_pct": node_ram["eviction_threshold_pct"],
                },
                "vram": {
                    "used_bytes": used_vram,
                    "total_bytes": total_vram,
                    "loading_detectors_bytes": loading_vram,
                    "observed_gpus": observed_gpus,
                },
            },
            "detectors": detectors,
        }


def _get_node_ram() -> dict:
    """Get system RAM total and used from the Kubernetes Node API and Metrics Server.

    Uses the node's capacity for total RAM and the Metrics Server for current
    usage. This matches the kubelet's view of memory, which drives pod eviction.
    Also extracts the kubelet's soft eviction threshold.
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


def _query_all_pod_gpus(inference_pods: list[tuple]) -> dict[str, dict | None]:
    """Query GPU data from each inference pod's HTTP endpoint."""
    return {pod.metadata.name: _query_pod_gpu(pod) for pod, _, _, _ in inference_pods}


def _build_gpu_summary(gpu_responses: dict[str, dict | None]) -> tuple[list, int, int]:
    """Aggregate GPU device observations across all queried pods.

    Returns (sorted_observed_gpus, total_vram_bytes, used_vram_bytes). Each
    entry in `sorted_observed_gpus` has keys `name`, `index`, `used_bytes`,
    `total_bytes`.
    """
    observed_gpus: dict[str, dict] = {}
    all_gpus_total = 0
    all_gpus_used = 0

    for gpu_data in gpu_responses.values():
        if gpu_data is None:
            continue
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
            if existing is None or gpu_total > existing.get("total_bytes", 0):
                observed_gpus[key] = {
                    "name": gpu_name,
                    "index": gpu_index,
                    "used_bytes": gpu_used,
                    "total_bytes": gpu_total,
                }
            elif gpu_used > existing.get("used_bytes", 0):
                existing["used_bytes"] = gpu_used

        all_gpus_total = max(all_gpus_total, pod_total)
        all_gpus_used = max(all_gpus_used, pod_used)

    sorted_gpus = sorted(
        observed_gpus.values(),
        key=lambda g: (
            g.get("index") if isinstance(g.get("index"), int) else 1_000_000,
            g.get("name") or "",
        ),
    )
    return sorted_gpus, all_gpus_total, all_gpus_used


def _attribute_detector_resources(
    inference_pods: list[tuple],
    active_pods: set[str],
    gpu_responses: dict[str, dict | None],
    ram_by_pod: dict[str, int],
) -> tuple[list, int, int]:
    """Attribute VRAM and RAM usage to individual detectors or loading totals.

    Returns (detectors_list, loading_vram_bytes, loading_ram_bytes). Each
    detector entry has the nested shape:
        {"detector_id": ..., "ram": {...}, "vram": {...}}
    where the inner objects have `primary_bytes`, `oodd_bytes`, `total_bytes`.
    """
    detectors: dict[str, dict] = {}
    loading_vram_bytes = 0
    loading_ram_bytes = 0

    def _blank_resource() -> dict:
        return {"primary_bytes": None, "oodd_bytes": None, "total_bytes": 0}

    for pod, det_id, is_oodd, _is_ready in inference_pods:
        gpu_data = gpu_responses.get(pod.metadata.name)
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
                "ram": _blank_resource(),
                "vram": _blank_resource(),
            }
        det = detectors[det_id]
        slot = "oodd_bytes" if is_oodd else "primary_bytes"
        det["vram"][slot] = (det["vram"][slot] or 0) + process_vram
        det["ram"][slot] = (det["ram"][slot] or 0) + process_ram
        det["vram"]["total_bytes"] = (det["vram"]["primary_bytes"] or 0) + (det["vram"]["oodd_bytes"] or 0)
        det["ram"]["total_bytes"] = (det["ram"]["primary_bytes"] or 0) + (det["ram"]["oodd_bytes"] or 0)

    return list(detectors.values()), loading_vram_bytes, loading_ram_bytes


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
