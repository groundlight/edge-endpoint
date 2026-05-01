"""Collects per-detector GPU, VRAM, RAM, and CPU usage for the status page.

GPU and VRAM data comes from each inference pod's /v2/gpu-usage HTTP endpoint.
RAM data comes from the Kubernetes Metrics Server (metrics.k8s.io/v1beta1).
System-level RAM and CPU use the Kubernetes Node API so that the numbers match
the kubelet's view of memory (which drives eviction decisions).

RAM used by non-inference pods in the edge namespace (the edge-endpoint
server itself plus sidecars like splunk, opentelemetry-collector, etc.) is
reported as a single `edge_endpoint_bytes` bucket on `system.ram`.
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation

import requests
from kubernetes import client, config

from app.metrics.system_metrics import _DATETIME_MIN_UTC, _pod_is_ready, get_namespace

logger = logging.getLogger(__name__)

GPU_ENDPOINT_PORT = 8000
GPU_ENDPOINT_PATH = "/v2/gpu-usage"
HTTP_TIMEOUT_SEC = 2
GPU_QUERY_MAX_WORKERS = 16

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
_K8S_MEM_RE = re.compile(r"^(\d+(?:\.\d+)?)([A-Za-z]{1,2})?$")
_K8S_CPU_SUFFIX_TO_MILLICORES = {
    "n": Decimal("0.000001"),
    "u": Decimal("0.001"),
    "m": Decimal("1"),
}
_K8S_CPU_RE = re.compile(r"^(\d+(?:\.\d+)?)([num])?$")


def _parse_k8s_memory(quantity: str) -> int:
    """Parse a Kubernetes memory quantity string (e.g. '524288Ki', '1.5Gi') into bytes.

    Kubelet-emitted values are almost always integers, but resource quantities
    can legally be fractional, so we accept those too. Unparseable inputs log
    a warning and return 0 rather than silently failing.
    """
    m = _K8S_MEM_RE.match(quantity)
    if not m:
        logger.warning("Could not parse Kubernetes memory quantity %r; returning 0", quantity)
        return 0
    value = float(m.group(1))
    suffix = m.group(2)
    multiplier = _K8S_MEM_SUFFIXES.get(suffix, 1) if suffix else 1
    return int(value * multiplier)


def _parse_k8s_cpu(quantity: str) -> float:
    """Parse a Kubernetes CPU quantity string into millicores."""
    m = _K8S_CPU_RE.match(quantity)
    if not m:
        logger.warning("Could not parse Kubernetes CPU quantity %r; returning 0", quantity)
        return 0.0
    try:
        value = Decimal(m.group(1))
    except InvalidOperation:
        logger.warning("Could not parse Kubernetes CPU quantity %r; returning 0", quantity)
        return 0.0

    suffix = m.group(2)
    multiplier = _K8S_CPU_SUFFIX_TO_MILLICORES.get(suffix, Decimal("1000")) if suffix else Decimal("1000")
    return float(value * multiplier)


def _percentage(numerator: float, denominator: float) -> float:
    """Return a percentage, or 0.0 when the denominator is zero."""
    if denominator <= 0:
        return 0.0
    return numerator / denominator * 100


class ResourceMetricsCollector:
    """Collects GPU, VRAM, RAM, and CPU usage for status reporting.

    The emitted payload is grouped by resource type at the system level and
    per-detector so existing RAM/VRAM consumers remain stable while newer GPU
    and CPU utilization metrics can be added.
    """

    def collect(self) -> dict:
        """Build the `/status/resources.json` payload.

        Returns a dict with two top-level keys:
            - `system`: node-wide `cpu`, `ram`, `vram`, and `gpu` totals, plus
              aggregate buckets for currently-loading detectors, edge-endpoint
              platform overhead, and the list of observed GPU devices.
            - `detectors`: a list of per-detector entries, each with nested
              `ram`, `vram`, and `gpu` objects.

        If called outside a Kubernetes cluster, returns `{"error": "..."}`.
        """
        try:
            config.load_incluster_config()
        except config.ConfigException:
            logger.warning("Not running in cluster, cannot collect resource metrics")
            return {"error": "Not running in a Kubernetes cluster"}

        namespace = get_namespace()
        v1 = client.CoreV1Api()
        pod_list = v1.list_namespaced_pod(namespace=namespace)
        inference_pods = _find_inference_pods(pod_list)
        node_resources = _get_node_resources(v1)
        ram_by_pod = _get_pod_ram_metrics(namespace)

        if inference_pods:
            active_pods = _pick_active_pods(inference_pods)
            gpu_responses = _query_all_pod_gpus(inference_pods)
            observed_gpus, gpu_devices, total_vram, used_vram, gpu_compute_pct, gpu_memory_bw_pct = _build_gpu_summary(
                gpu_responses
            )
            (
                detectors,
                loading_vram,
                loading_ram,
                loading_gpu_compute_pct,
                loading_gpu_memory_bw_pct,
            ) = _attribute_detector_resources(
                inference_pods,
                active_pods,
                gpu_responses,
                ram_by_pod,
            )
        else:
            observed_gpus, gpu_devices, total_vram, used_vram = [], [], 0, 0
            gpu_compute_pct, gpu_memory_bw_pct = 0.0, 0.0
            detectors, loading_vram, loading_ram = [], 0, 0
            loading_gpu_compute_pct, loading_gpu_memory_bw_pct = 0.0, 0.0

        # Anything in the namespace that isn't a recognised Running inference
        # pod counts as "edge-endpoint platform overhead": the edge-endpoint
        # server itself, plus sidecars (network-healer, splunk, otel, etc.).
        # This is a broad heuristic; a stray Job or a user-deployed pod in the
        # edge namespace would also land in this bucket. Acceptable for now,
        # since the namespace is chart-owned and unlikely to host foreign pods.
        inference_pod_names = {pod.metadata.name for pod, _, _, _ in inference_pods}
        edge_endpoint_ram = sum(
            bytes_used for name, bytes_used in ram_by_pod.items() if name not in inference_pod_names
        )

        return {
            "system": {
                "cpu": node_resources["cpu"],
                "ram": {
                    "used_bytes": node_resources["ram"]["used"],
                    "total_bytes": node_resources["ram"]["total"],
                    "loading_detectors_bytes": loading_ram,
                    "edge_endpoint_bytes": edge_endpoint_ram,
                    "eviction_threshold_pct": node_resources["ram"]["eviction_threshold_pct"],
                },
                "vram": {
                    "used_bytes": used_vram,
                    "total_bytes": total_vram,
                    "loading_detectors_bytes": loading_vram,
                    "edge_endpoint_bytes": 0,  # Only inference pods consume VRAM
                    "observed_gpus": observed_gpus,
                },
                "gpu": {
                    "compute_utilization_pct": gpu_compute_pct,
                    "memory_bandwidth_pct": gpu_memory_bw_pct,
                    "loading_detectors_compute_utilization_pct": loading_gpu_compute_pct,
                    "loading_detectors_memory_bandwidth_pct": loading_gpu_memory_bw_pct,
                    "devices": gpu_devices,
                },
            },
            "detectors": detectors,
        }


def _get_node_resources(v1: "client.CoreV1Api") -> dict:
    """Get node RAM details and overall CPU utilization from Kubernetes APIs.

    Uses node capacity for RAM and CPU totals, and Metrics Server for current
    usage. RAM keeps the existing detailed shape, while CPU is exposed as an
    overall utilization percentage.
    """
    try:
        node_name = os.environ.get("NODE_NAME")
        if not node_name:
            raise ValueError("NODE_NAME env var not set; cannot identify our node")
        # NODE_NAME is injected by the helm chart via the downward API
        # (spec.nodeName) so we always report capacity for the node the
        # edge-endpoint pod is actually running on, even on a multi-node cluster.
        node = v1.read_node(name=node_name)
        total_ram = _parse_k8s_memory(node.status.capacity.get("memory", "0"))
        total_cpu_millicores = _parse_k8s_cpu(node.status.capacity.get("cpu", "0"))

        custom = client.CustomObjectsApi()
        node_metrics = custom.list_cluster_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            plural="nodes",
        )
        used_ram = 0
        used_cpu_millicores = 0.0
        for item in node_metrics.get("items", []):
            if item.get("metadata", {}).get("name") == node.metadata.name:
                usage = item.get("usage", {})
                used_ram = _parse_k8s_memory(usage.get("memory", "0"))
                used_cpu_millicores = _parse_k8s_cpu(usage.get("cpu", "0"))
                break

        eviction_pct = _parse_eviction_threshold(node)
        cpu_utilization_pct = _percentage(used_cpu_millicores, total_cpu_millicores)

        return {
            "ram": {"total": total_ram, "used": used_ram, "eviction_threshold_pct": eviction_pct},
            "cpu": {"utilization_pct": cpu_utilization_pct},
        }
    except Exception:
        logger.error("Failed to get node resources from Kubernetes APIs", exc_info=True)
        return {
            "ram": {"total": 0, "used": 0, "eviction_threshold_pct": None},
            "cpu": {"utilization_pct": 0.0},
        }


_EVICTION_MEM_RE = re.compile(r"memory\.available<(\d+)%")


def _parse_eviction_threshold(node) -> int | None:
    """Extract the soft memory eviction threshold from the k3s node-args annotation.

    Returns the percentage of total RAM at which the kubelet starts evicting
    pods (i.e. 100 - available%), or None if not found. Reads the
    `k3s.io/node-args` annotation for eviction-soft first, then eviction-hard.
    This is k3s-specific; on non-k3s clusters this will always return None and
    the UI will simply omit the threshold marker.

    Only the percentage form (`memory.available<10%`) is supported. If the
    edge is configured with an absolute threshold (`memory.available<500Mi`)
    this returns None and the donut will omit the marker.
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
        # Non-running pods or pods without IP addresses cannot be queried for GPU metrics,
        # so we will not include them here.
        if not pod.status or pod.status.phase != "Running":
            continue
        if not pod.status.pod_ip:
            continue
        annotations = pod.metadata.annotations or {}
        det_id = annotations.get("groundlight.dev/detector-id")
        model_name = annotations.get("groundlight.dev/model-name")

        # Pods lacking det_id and model_name annotations are not inference pods
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
            best = max(ready, key=lambda e: e[0].metadata.creation_timestamp or _DATETIME_MIN_UTC)
            active.add(best[0].metadata.name)
    return active


def _query_pod_gpu(pod) -> dict | None:
    """HTTP GET /v2/gpu-usage on a single inference pod. Returns parsed JSON or None."""
    url = f"http://{pod.status.pod_ip}:{GPU_ENDPOINT_PORT}{GPU_ENDPOINT_PATH}"
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT_SEC)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.debug(f"Failed to query GPU usage from pod {pod.metadata.name} at {url}")
        return None


def _query_all_pod_gpus(inference_pods: list[tuple]) -> dict[str, dict | None]:
    """Query GPU data from every inference pod's HTTP endpoint in parallel.

    Runs the per-pod HTTP GETs concurrently so a single slow/hung pod can't
    stall the whole endpoint. Worst-case latency is ~HTTP_TIMEOUT_SEC rather
    than N * HTTP_TIMEOUT_SEC.
    """
    pods = [pod for pod, _, _, _ in inference_pods]
    if not pods:
        return {}
    max_workers = min(GPU_QUERY_MAX_WORKERS, len(pods))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="gpu-query") as pool:
        results = list(pool.map(_query_pod_gpu, pods))
    return {pod.metadata.name: data for pod, data in zip(pods, results)}


def _build_gpu_summary(gpu_responses: dict[str, dict | None]) -> tuple[list, list, int, int, float, float]:
    """Aggregate GPU device observations across all queried pods.

    Returns compatibility VRAM device entries, v2-style GPU device entries,
    aggregate VRAM bytes, and average device-wide GPU utilization.
    """
    devices_by_key: dict[str, dict] = {}
    all_gpus_total = 0
    all_gpus_used = 0

    for gpu_data in gpu_responses.values():
        if gpu_data is None:
            continue
        gpu_devices = gpu_data.get("devices") or []
        pod_total = 0
        pod_used = 0
        for device in gpu_devices:
            gpu_name = device.get("name")
            gpu_total = device.get("vram_total_bytes", 0)
            gpu_used = device.get("vram_used_bytes", 0)
            gpu_free = device.get("vram_free_bytes", 0)
            gpu_uuid = device.get("uuid")
            gpu_index = device.get("index")
            compute_pct = float(device.get("compute_utilization_pct") or 0.0)
            memory_bw_pct = float(device.get("memory_bandwidth_pct") or 0.0)
            pod_total += gpu_total
            pod_used += gpu_used
            if not gpu_name:
                continue
            key = str(gpu_uuid or f"{gpu_name}:{gpu_index}")
            existing = devices_by_key.get(key)
            if existing is None:
                devices_by_key[key] = {
                    "index": gpu_index,
                    "uuid": gpu_uuid,
                    "name": gpu_name,
                    "vram_total_bytes": gpu_total,
                    "vram_used_bytes": gpu_used,
                    "vram_free_bytes": gpu_free,
                    "compute_utilization_pct": compute_pct,
                    "memory_bandwidth_pct": memory_bw_pct,
                }
            else:
                existing["vram_total_bytes"] = max(existing.get("vram_total_bytes", 0), gpu_total)
                existing["vram_used_bytes"] = max(existing.get("vram_used_bytes", 0), gpu_used)
                existing["vram_free_bytes"] = max(existing.get("vram_free_bytes", 0), gpu_free)
                existing["compute_utilization_pct"] = max(existing.get("compute_utilization_pct", 0.0), compute_pct)
                existing["memory_bandwidth_pct"] = max(existing.get("memory_bandwidth_pct", 0.0), memory_bw_pct)

        # Every inference pod on a given node sees the same physical GPUs via
        # the nvidia device plugin, so we take the max across pods (dedupe)
        # rather than summing (which would overcount). If that invariant ever
        # breaks (e.g. GPU MIG or multi-instance scheduling), this should be
        # revisited.
        all_gpus_total = max(all_gpus_total, pod_total)
        all_gpus_used = max(all_gpus_used, pod_used)

    sorted_devices = sorted(
        devices_by_key.values(),
        key=lambda g: (
            g.get("index") if isinstance(g.get("index"), int) else 1_000_000,
            g.get("name") or "",
        ),
    )
    observed_gpus = [
        {
            "name": device["name"],
            "index": device["index"],
            "used_bytes": device["vram_used_bytes"],
            "total_bytes": device["vram_total_bytes"],
        }
        for device in sorted_devices
    ]
    if sorted_devices:
        compute_pct = sum(device["compute_utilization_pct"] for device in sorted_devices) / len(sorted_devices)
        memory_bw_pct = sum(device["memory_bandwidth_pct"] for device in sorted_devices) / len(sorted_devices)
    else:
        compute_pct = 0.0
        memory_bw_pct = 0.0
    return observed_gpus, sorted_devices, all_gpus_total, all_gpus_used, compute_pct, memory_bw_pct


def _attribute_detector_resources(
    inference_pods: list[tuple],
    active_pods: set[str],
    gpu_responses: dict[str, dict | None],
    ram_by_pod: dict[str, int],
) -> tuple[list, int, int, float, float]:
    """Attribute VRAM, GPU utilization, and RAM to individual detectors or loading totals.

    Returns detector entries, loading VRAM/RAM, and loading GPU utilization
    totals. RAM/VRAM objects have primary, OODD, and total byte fields; GPU
    objects have primary, OODD, and total utilization fields.
    """
    detectors: dict[str, dict] = {}
    loading_vram_bytes = 0
    loading_ram_bytes = 0
    loading_gpu_compute_pct = 0.0
    loading_gpu_memory_bw_pct = 0.0

    def _blank_resource() -> dict:
        return {"primary_bytes": None, "oodd_bytes": None, "total_bytes": 0}

    def _blank_gpu() -> dict:
        return {
            "primary_compute_utilization_pct": None,
            "oodd_compute_utilization_pct": None,
            "total_compute_utilization_pct": 0.0,
            "primary_memory_bandwidth_pct": None,
            "oodd_memory_bandwidth_pct": None,
            "total_memory_bandwidth_pct": 0.0,
        }

    for pod, det_id, is_oodd, _is_ready in inference_pods:
        gpu_data = gpu_responses.get(pod.metadata.name)
        process_info = (gpu_data.get("process") or {}) if gpu_data else {}
        process_vram = process_info.get("vram_used_bytes") or 0
        process_compute_pct = float(process_info.get("compute_utilization_pct") or 0.0)
        process_memory_bw_pct = float(process_info.get("memory_bandwidth_pct") or 0.0)
        process_ram = ram_by_pod.get(pod.metadata.name, 0)

        if pod.metadata.name not in active_pods:
            loading_vram_bytes += process_vram
            loading_ram_bytes += process_ram
            loading_gpu_compute_pct = min(loading_gpu_compute_pct + process_compute_pct, 100.0)
            loading_gpu_memory_bw_pct = min(loading_gpu_memory_bw_pct + process_memory_bw_pct, 100.0)
            continue

        if det_id not in detectors:
            detectors[det_id] = {
                "detector_id": det_id,
                "ram": _blank_resource(),
                "vram": _blank_resource(),
                "gpu": _blank_gpu(),
            }
        det = detectors[det_id]
        bytes_slot = "oodd_bytes" if is_oodd else "primary_bytes"
        compute_slot = "oodd_compute_utilization_pct" if is_oodd else "primary_compute_utilization_pct"
        memory_slot = "oodd_memory_bandwidth_pct" if is_oodd else "primary_memory_bandwidth_pct"
        det["vram"][bytes_slot] = (det["vram"][bytes_slot] or 0) + process_vram
        det["ram"][bytes_slot] = (det["ram"][bytes_slot] or 0) + process_ram
        det["gpu"][compute_slot] = min((det["gpu"][compute_slot] or 0.0) + process_compute_pct, 100.0)
        det["gpu"][memory_slot] = min((det["gpu"][memory_slot] or 0.0) + process_memory_bw_pct, 100.0)
        det["vram"]["total_bytes"] = (det["vram"]["primary_bytes"] or 0) + (det["vram"]["oodd_bytes"] or 0)
        det["ram"]["total_bytes"] = (det["ram"]["primary_bytes"] or 0) + (det["ram"]["oodd_bytes"] or 0)
        det["gpu"]["total_compute_utilization_pct"] = min(
            (det["gpu"]["primary_compute_utilization_pct"] or 0.0)
            + (det["gpu"]["oodd_compute_utilization_pct"] or 0.0),
            100.0,
        )
        det["gpu"]["total_memory_bandwidth_pct"] = min(
            (det["gpu"]["primary_memory_bandwidth_pct"] or 0.0)
            + (det["gpu"]["oodd_memory_bandwidth_pct"] or 0.0),
            100.0,
        )

    return (
        list(detectors.values()),
        loading_vram_bytes,
        loading_ram_bytes,
        loading_gpu_compute_pct,
        loading_gpu_memory_bw_pct,
    )


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
