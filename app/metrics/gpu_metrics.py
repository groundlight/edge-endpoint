"""Collects per-detector GPU usage by querying each inference pod's /gpu-usage HTTP endpoint."""

import logging

import requests
from kubernetes import client, config

from app.metrics.system_metrics import _pod_is_ready, get_namespace

logger = logging.getLogger(__name__)

GPU_ENDPOINT_PORT = 8000
GPU_ENDPOINT_PATH = "/gpu-usage"
HTTP_TIMEOUT_SEC = 2


class GpuMetricsCollector:
    """Collects GPU usage per inference pod via HTTP to each pod's /gpu-usage endpoint."""

    def collect(self) -> dict:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            logger.warning("Not running in cluster, cannot collect GPU metrics")
            return {"error": "Not running in a Kubernetes cluster"}

        namespace = get_namespace()
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(namespace=namespace)

        inference_pods = _find_inference_pods(pods)
        if not inference_pods:
            return {
                "total_vram_bytes": 0,
                "used_vram_bytes": 0,
                "detectors": [],
                "loading_vram_bytes": 0,
                "observed_gpus": [],
            }

        active_pods = _pick_active_pods(inference_pods)

        detectors: dict[str, dict] = {}
        loading_vram_bytes = 0
        all_gpus_total = 0
        all_gpus_used = 0
        observed_gpus: dict[str, dict] = {}

        for pod, det_id, is_oodd, _is_ready in inference_pods:
            gpu_data = _query_pod_gpu(pod)
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

            pod_info = gpu_data.get("pod") or {}
            process_vram = pod_info.get("vram_bytes") or 0

            if pod.metadata.name not in active_pods:
                loading_vram_bytes += process_vram
                continue

            if det_id not in detectors:
                detectors[det_id] = {
                    "detector_id": det_id,
                    "primary_vram_bytes": None,
                    "oodd_vram_bytes": None,
                    "total_vram_bytes": 0,
                }
            det = detectors[det_id]
            if is_oodd:
                det["oodd_vram_bytes"] = (det["oodd_vram_bytes"] or 0) + process_vram
            else:
                det["primary_vram_bytes"] = (det["primary_vram_bytes"] or 0) + process_vram
            det["total_vram_bytes"] = (det["primary_vram_bytes"] or 0) + (det["oodd_vram_bytes"] or 0)

        return {
            "total_vram_bytes": all_gpus_total,
            "used_vram_bytes": all_gpus_used,
            "detectors": list(detectors.values()),
            "loading_vram_bytes": loading_vram_bytes,
            "observed_gpus": sorted(
                observed_gpus.values(),
                key=lambda g: (
                    g.get("index") if isinstance(g.get("index"), int) else 1_000_000,
                    g.get("name") or "",
                ),
            ),
        }


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
    Every other pod's VRAM will be counted as "loading".
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
