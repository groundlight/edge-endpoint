"""Resource sampler: thin wrapper over groundlight_helpers._get_resources.

Runs in its own multiprocessing.Process. Builds ExperimentalApi() *after* fork
to avoid pickling the SDK client across the process boundary.
"""

import logging
import multiprocessing as mp
import sys
import time

from app_benchmark.ipc import GpuDeviceSample, SystemSample

# `groundlight_helpers` is imported lazily inside the worker so unit tests that
# stub it can swap it out before the worker imports.

logger = logging.getLogger(__name__)

_ERROR_LOG_INTERVAL_S = 30.0


def _parse(resources: dict, ts: float) -> SystemSample:
    if "error" in resources:
        return SystemSample(
            ts=ts, cpu_total_pct=0.0, ram_used_bytes=0, ram_total_bytes=0,
            gpu_compute_total_pct=0.0, gpu_vram_used_bytes=0, gpu_vram_total_bytes=0,
            gpu_devices=[], loading_detectors_bytes=0,
            error=str(resources.get("error")),
        )
    system = resources.get("system", {}) or {}
    cpu = system.get("cpu_utilization_pct", {}) or {}
    ram = system.get("ram_bytes", {}) or {}
    gpu = system.get("gpu", {}) or {}
    vram = gpu.get("vram_bytes", {}) or {}
    compute = gpu.get("compute_utilization_pct", {}) or {}

    devices: list[GpuDeviceSample] = []
    for d in gpu.get("devices", []) or []:
        d_vram = d.get("vram_bytes", {}) or {}
        devices.append(GpuDeviceSample(
            index=int(d.get("index", -1)),
            uuid=d.get("uuid"),
            name=str(d.get("name", "")),
            vram_used_bytes=int(d_vram.get("used", 0)),
            vram_total_bytes=int(d_vram.get("total", 0)),
            compute_pct=float(d.get("compute_utilization_pct", 0.0) or 0.0),
            memory_bandwidth_pct=float(d.get("memory_bandwidth_pct", 0.0) or 0.0),
        ))

    return SystemSample(
        ts=ts,
        cpu_total_pct=float(cpu.get("total", 0.0) or 0.0),
        ram_used_bytes=int(ram.get("used", 0) or 0),
        ram_total_bytes=int(ram.get("total", 0) or 0),
        gpu_compute_total_pct=float(compute.get("total", 0.0) or 0.0),
        gpu_vram_used_bytes=int(vram.get("used", 0) or 0),
        gpu_vram_total_bytes=int(vram.get("total", 0) or 0),
        gpu_devices=devices,
        loading_detectors_bytes=int(vram.get("loading_detectors", 0) or 0),
    )


def run_monitor(
    sample_hz: float,
    sample_queue: "mp.Queue",
    frame_queue: "mp.Queue",
    stop_event,
    edge_url: str,
) -> None:
    """Entry point. Polls /status/resources.json at sample_hz until stop_event is set."""

    # Imports happen post-fork so tests can monkey-patch.
    from groundlight import ExperimentalApi  # noqa: PLC0415
    import groundlight_helpers as glh  # noqa: PLC0415

    period = 1.0 / sample_hz if sample_hz > 0 else 0.5
    # Construct ExperimentalApi against the EDGE endpoint, not the cloud.
    # (ExperimentalApi() with no args picks up GROUNDLIGHT_ENDPOINT which
    # typically points at the cloud — that returns 404 for /status/resources.json.)
    gl = ExperimentalApi(endpoint=edge_url)
    last_error_log = 0.0

    while not stop_event.is_set():
        loop_start = time.time()
        ts = loop_start
        try:
            resources = glh._get_resources(gl, timeout=5.0)
            sample = _parse(resources, ts=ts)
        except Exception as exc:
            sample = SystemSample(
                ts=ts, cpu_total_pct=0.0, ram_used_bytes=0, ram_total_bytes=0,
                gpu_compute_total_pct=0.0, gpu_vram_used_bytes=0, gpu_vram_total_bytes=0,
                gpu_devices=[], loading_detectors_bytes=0, error=str(exc),
            )
            now = time.time()
            if now - last_error_log > _ERROR_LOG_INTERVAL_S:
                print(f"[monitor] resource fetch failed: {exc}", file=sys.stderr)
                last_error_log = now

        try:
            sample_queue.put_nowait(sample)
        except Exception:
            pass

        elapsed = time.time() - loop_start
        remaining = period - elapsed
        if remaining > 0:
            stop_event.wait(remaining)
