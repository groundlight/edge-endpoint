import json
import multiprocessing
import os
import sys
import time
from datetime import datetime
from typing import Optional

from groundlight import ExperimentalApi

import groundlight_helpers as glh


_ERROR_LOG_INTERVAL_SEC = 30.0


class SystemMonitor:
    """Polls the Edge Endpoint's /status/resources.json in a background process and logs results.

    Emits one `event: "cpu"` and one `event: "gpu"` JSONL record per tick, matching
    the schema parse_load_test_logs.py consumes. Only system-level totals are recorded;
    per-detector / loading_detectors / other buckets are intentionally ignored
    (NVML windowing skew, container PID mismatch — see PR #394 review discussion).

    CPU/RAM samples are bounded by Kubernetes Metrics Server cadence (~15s); GPU/VRAM
    are fresh-on-call. Sampling below 15s gives repeated CPU/RAM but fresher GPU.
    """

    def __init__(self, log_file: str, sample_interval: float = 5.0):
        self.log_file = log_file
        self.sample_interval = sample_interval
        self._stop_event = multiprocessing.Event()
        self._process: Optional[multiprocessing.Process] = None

    def start(self) -> None:
        if self._process and self._process.is_alive():
            return
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        self._stop_event.clear()
        self._process = multiprocessing.Process(
            target=self._monitor_loop,
            args=(self.log_file, self.sample_interval, self._stop_event),
        )
        self._process.start()

    def stop(self) -> None:
        if not self._process:
            return
        self._stop_event.set()
        self._process.join()
        self._process = None

    @staticmethod
    def _monitor_loop(log_file: str, sample_interval: float, stop_event) -> None:
        gl = ExperimentalApi()
        last_error_log_ts = 0.0

        while not stop_event.is_set():
            loop_start = time.time()
            event_ts = time.time()
            timestamp = datetime.fromtimestamp(event_ts).strftime("%Y-%m-%d %H:%M:%S")

            try:
                resources = glh._get_resources(gl)
            except Exception as exc:
                now = time.time()
                if now - last_error_log_ts > _ERROR_LOG_INTERVAL_SEC:
                    print(
                        f"[SystemMonitor] Failed to fetch /status/resources.json: {exc}",
                        file=sys.stderr,
                    )
                    last_error_log_ts = now
                elapsed = time.time() - loop_start
                remaining = sample_interval - elapsed
                if remaining > 0:
                    stop_event.wait(remaining)
                continue

            system = resources.get("system", {})
            cpu_total = system.get("cpu_utilization_pct", {}).get("total", 0.0)
            ram = system.get("ram_bytes", {})
            ram_total = ram.get("total", 0)
            ram_used = ram.get("used", 0)
            memory_percent = (ram_used / ram_total * 100) if ram_total else 0.0

            gpu = system.get("gpu", {})
            gpu_compute_total = gpu.get("compute_utilization_pct", {}).get("total", 0.0)
            vram = gpu.get("vram_bytes", {})
            vram_total = vram.get("total", 0)
            vram_used = vram.get("used", 0)
            vram_percent = (vram_used / vram_total * 100) if vram_total else 0.0

            SystemMonitor._append_log(
                log_file,
                {
                    "asctime": timestamp,
                    "ts": event_ts,
                    "event": "cpu",
                    "cpu_percent": round(cpu_total, 2),
                    "memory_percent": round(memory_percent, 2),
                },
            )
            SystemMonitor._append_log(
                log_file,
                {
                    "asctime": timestamp,
                    "ts": event_ts,
                    "event": "gpu",
                    "gpu_utilization": round(gpu_compute_total, 2),
                    "vram_utilization": round(vram_percent, 2),
                },
            )

            elapsed = time.time() - loop_start
            remaining = sample_interval - elapsed
            if remaining > 0:
                stop_event.wait(remaining)

    @staticmethod
    def _append_log(log_file: str, payload: dict) -> None:
        with open(log_file, "a", encoding="utf-8") as log:
            log.write(json.dumps(payload) + "\n")
