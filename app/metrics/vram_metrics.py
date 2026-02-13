"""Collects per-detector VRAM usage by exec'ing nvidia-smi in inference pods.

PID namespace isolation on modern kernels prevents containers from seeing their host PIDs,
so we cannot directly map nvidia-smi processes to pods. Instead, we exec nvidia-smi in a
single inference pod to get the global process list, then correlate nvidia-smi processes
with inference pods by matching PID order to pod creation order. This works because PIDs
are assigned monotonically and pod creation order is deterministic.
"""

import logging
import time
from dataclasses import dataclass

from kubernetes import client, config
from kubernetes.stream import stream

from app.metrics.system_metrics import _pod_is_ready, get_namespace

logger = logging.getLogger(__name__)

MIB_TO_BYTES = 1024 * 1024

# Collects GPU info and per-process VRAM in a single exec call. Only needs to run in ONE pod
# since nvidia-smi sees all GPUs and all processes on the host regardless of PID namespace.
_NVIDIA_SMI_SCRIPT = """\
echo "---GPU---"
nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.used,memory.free --format=csv,noheader,nounits 2>/dev/null
echo "---PROCS---"
nvidia-smi --query-compute-apps=pid,used_gpu_memory,gpu_uuid --format=csv,noheader,nounits 2>/dev/null
"""


@dataclass
class GpuInfo:
    index: int
    uuid: str
    name: str
    total_bytes: int
    used_bytes: int
    free_bytes: int


@dataclass
class GpuProcess:
    """A single GPU process as reported by nvidia-smi."""

    pid: int
    vram_bytes: int
    gpu_uuid: str


class VramMetricsCollector:
    """Collects VRAM usage per inference pod via k8s exec + nvidia-smi."""

    def __init__(self, cache_ttl_sec: float = 1.0):
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

        # Exec nvidia-smi in any running inference pod to get global GPU state
        gpu_infos, gpu_processes = None, None
        for pod, _, _, _ in inference_pods:
            result = _exec_nvidia_smi(v1, pod.metadata.name, namespace)
            if result is not None:
                gpu_infos, gpu_processes = result
                break

        if gpu_infos is None:
            return {"gpus": [], "detectors": [], "loading_vram_bytes": 0}

        return _build_response(gpu_infos, gpu_processes, inference_pods)


def _find_inference_pods(pod_list) -> list[tuple]:
    """Return (pod, detector_id, is_oodd, is_ready) for running inference pods, sorted by creation time."""
    results = []
    for pod in pod_list.items:
        if pod.status.phase != "Running":
            continue
        annotations = pod.metadata.annotations or {}
        det_id = annotations.get("groundlight.dev/detector-id")
        model_name = annotations.get("groundlight.dev/model-name")
        if not det_id or not model_name:
            continue
        is_oodd = model_name.endswith("/oodd")
        is_ready = _pod_is_ready(pod)
        results.append((pod, det_id, is_oodd, is_ready))
    # Sort by creation timestamp so ordering matches PID assignment order
    results.sort(key=lambda x: x[0].metadata.creation_timestamp or "")
    return results


def _exec_nvidia_smi(v1, pod_name: str, namespace: str) -> tuple[list[GpuInfo], list[GpuProcess]] | None:
    """Exec nvidia-smi in a single pod and parse the output."""
    try:
        output = stream(
            v1.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=namespace,
            container="inference-server",
            command=["/bin/sh", "-c", _NVIDIA_SMI_SCRIPT],
            stderr=False,
            stdin=False,
            stdout=True,
            tty=False,
            _request_timeout=10,
        )
    except Exception:
        logger.exception(f"k8s exec failed for pod {pod_name}")
        return None

    return _parse_nvidia_smi_output(output)


def _parse_nvidia_smi_output(output: str) -> tuple[list[GpuInfo], list[GpuProcess]] | None:
    """Parse nvidia-smi output into GPU info and process lists."""
    sections: dict[str, list[str]] = {"GPU": [], "PROCS": []}
    current = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("---") and stripped.endswith("---"):
            current = stripped.strip("-")
        elif current in sections and stripped:
            sections[current].append(stripped)

    gpu_infos = []
    for line in sections["GPU"]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            gpu_infos.append(
                GpuInfo(
                    index=int(parts[0]),
                    uuid=parts[1],
                    name=parts[2],
                    total_bytes=int(parts[3]) * MIB_TO_BYTES,
                    used_bytes=int(parts[4]) * MIB_TO_BYTES,
                    free_bytes=int(parts[5]) * MIB_TO_BYTES,
                )
            )
        except (ValueError, IndexError):
            logger.warning(f"Failed to parse GPU info line: {line}")

    if not gpu_infos:
        return None

    # Parse processes sorted by PID (ascending) to enable ordered matching with pods
    gpu_processes = []
    for line in sections["PROCS"]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            gpu_processes.append(
                GpuProcess(
                    pid=int(parts[0]),
                    vram_bytes=int(parts[1]) * MIB_TO_BYTES,
                    gpu_uuid=parts[2],
                )
            )
        except (ValueError, IndexError):
            pass
    gpu_processes.sort(key=lambda p: p.pid)

    return gpu_infos, gpu_processes


def _build_response(
    gpu_infos: list[GpuInfo],
    gpu_processes: list[GpuProcess],
    inference_pods: list[tuple],
) -> dict:
    """Map nvidia-smi processes to inference pods and build the response.

    nvidia-smi reports host-namespace PIDs which are not visible inside containers. Since PIDs
    are assigned monotonically and inference pods are sorted by creation time, we match processes
    to pods in order. If there are more nvidia-smi processes than inference pods, the extras are
    unattributed (they show up as "Other" in the frontend).

    Ready pods have their VRAM attributed to their detector. Non-ready pods (still loading models
    during rolling updates or initial deployments) have their VRAM summed into loading_vram_bytes.
    """
    gpus = {g.uuid: g for g in gpu_infos}
    detectors: dict[str, dict] = {}
    loading_vram_bytes = 0

    # Match processes to pods by sorted order (PID order ~ pod creation order)
    num_pods = len(inference_pods)
    for i, proc in enumerate(gpu_processes):
        if i >= num_pods:
            break  # More processes than pods -- extras are unattributed
        _, det_id, is_oodd, is_ready = inference_pods[i]

        if not is_ready:
            loading_vram_bytes += proc.vram_bytes
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
            det["oodd_vram_bytes"] = (det["oodd_vram_bytes"] or 0) + proc.vram_bytes
        else:
            det["primary_vram_bytes"] = (det["primary_vram_bytes"] or 0) + proc.vram_bytes
        det["total_vram_bytes"] = (det["primary_vram_bytes"] or 0) + (det["oodd_vram_bytes"] or 0)

    return {
        "gpus": [
            {
                "index": g.index,
                "uuid": g.uuid,
                "name": g.name,
                "total_bytes": g.total_bytes,
                "used_bytes": g.used_bytes,
                "free_bytes": g.free_bytes,
            }
            for g in sorted(gpus.values(), key=lambda g: g.index)
        ],
        "detectors": sorted(detectors.values(), key=lambda d: d["detector_id"]),
        "loading_vram_bytes": loading_vram_bytes,
    }
