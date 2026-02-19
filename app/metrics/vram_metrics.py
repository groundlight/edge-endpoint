"""Collects per-detector VRAM usage by querying each inference pod's /vram-usage HTTP endpoint."""

import logging
import time

import requests
from kubernetes import client, config

from app.metrics.system_metrics import _pod_is_ready, get_namespace

logger = logging.getLogger(__name__)

VRAM_ENDPOINT_PORT = 8000
VRAM_ENDPOINT_PATH = "/vram-usage"
HTTP_TIMEOUT_SEC = 2


class VramMetricsCollector:
    """Collects VRAM usage per inference pod via HTTP to each pod's /vram-usage endpoint."""

    def __init__(self, cache_ttl_sec: float = 30.0):
        self._cache_ttl_sec = cache_ttl_sec
        self._cached_result: dict | None = None
        self._cache_time: float = 0

    def collect(self) -> dict:
        now = time.monotonic()
        if self._cached_result is not None and (now - self._cache_time) < self._cache_ttl_sec:
            return self._cached_result

        result = self._collect_fresh()
        self._cached_result = result
        self._cache_time = now
        return result

    def _collect_fresh(self) -> dict:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            logger.warning("Not running in cluster, cannot collect VRAM metrics")
            return {"error": "Not running in a Kubernetes cluster"}

        v1 = client.CoreV1Api()
        namespace = get_namespace()
        pods = v1.list_namespaced_pod(namespace=namespace)

        inference_pods = _find_inference_pods(pods)
        if not inference_pods:
            return {"gpus": [], "detectors": [], "loading_vram_bytes": 0}

        selected = _select_one_pod_per_role(inference_pods)

        gpus: dict[str, dict] = {}
        detectors: dict[str, dict] = {}
        loading_vram_bytes = 0

        for pod, det_id, is_oodd, is_ready in selected:
            vram_data = _query_pod_vram(pod)
            if vram_data is None:
                continue

            process_vram = vram_data.get("process_vram_bytes") or 0
            gpu_info = vram_data.get("gpu")
            if gpu_info and gpu_info.get("uuid"):
                gpus[gpu_info["uuid"]] = gpu_info

            if not is_ready:
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

        gpu_list = sorted(gpus.values(), key=lambda g: g.get("index", 0))

        return {
            "gpus": gpu_list,
            "detectors": sorted(detectors.values(), key=lambda d: d["detector_id"]),
            "loading_vram_bytes": loading_vram_bytes,
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


def _select_one_pod_per_role(pods: list[tuple]) -> list[tuple]:
    """For each (detector_id, is_oodd) group, pick the newest ready pod.

    If no pod in the group is ready, pick the newest pod (so we can attempt to
    query it and report its VRAM as "loading").
    """
    groups: dict[tuple[str, bool], list[tuple]] = {}
    for entry in pods:
        _, det_id, is_oodd, _ = entry
        groups.setdefault((det_id, is_oodd), []).append(entry)

    selected = []
    for group in groups.values():
        ready = [e for e in group if e[3]]
        if ready:
            best = max(ready, key=lambda e: e[0].metadata.creation_timestamp or "")
        else:
            best = max(group, key=lambda e: e[0].metadata.creation_timestamp or "")
        selected.append(best)
    return selected


def _query_pod_vram(pod) -> dict | None:
    """HTTP GET /vram-usage on a single inference pod. Returns parsed JSON or None."""
    url = f"http://{pod.status.pod_ip}:{VRAM_ENDPOINT_PORT}{VRAM_ENDPOINT_PATH}"
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT_SEC)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.debug(f"Failed to query VRAM from pod {pod.metadata.name} at {url}")
        return None
