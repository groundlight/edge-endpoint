import json
import multiprocessing
import os
import time
from datetime import datetime
from typing import Optional

import psutil
import GPUtil


class SystemMonitor:
    """Monitors CPU and GPU utilization in a background process and logs results."""

    def __init__(self, log_file: str, sample_interval: float = 1.0):
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
    def _monitor_loop(log_file: str, sample_interval: float, stop_event: multiprocessing.Event) -> None:
        psutil.cpu_percent(interval=None)  # Prime cpu_percent measurement
        while not stop_event.is_set():
            loop_start = time.time()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cpu_percent = psutil.cpu_percent(interval=None)
            memory_percent = psutil.virtual_memory().percent
            SystemMonitor._append_log(
                log_file,
                {
                    "asctime": timestamp,
                    "event": "cpu",
                    "cpu_percent": round(cpu_percent, 2),
                    "memory_percent": round(memory_percent, 2),
                },
            )

            gpus = GPUtil.getGPUs()
            gpu_utilizations = [gpu.load * 100 for gpu in gpus]
            vram_utilizations = [gpu.memoryUtil * 100 for gpu in gpus]
            average_gpu_utilization = sum(gpu_utilizations) / len(gpu_utilizations) if gpu_utilizations else 0.0
            average_vram_utilization = sum(vram_utilizations) / len(vram_utilizations) if vram_utilizations else 0.0
            gpu_payload = {
                "asctime": timestamp,
                "event": "gpu",
                "gpu_utilization": round(average_gpu_utilization, 2),
                "vram_utilization": round(average_vram_utilization, 2),
                "gpus": [
                    {
                        "id": gpu.id,
                        "name": gpu.name,
                        "gpu_utilization": round(gpu.load * 100, 2),
                        "memory_utilization": round(gpu.memoryUtil * 100, 2),
                    }
                    for gpu in gpus
                ],
            }
            SystemMonitor._append_log(log_file, gpu_payload)

            elapsed = time.time() - loop_start
            remaining = sample_interval - elapsed
            if remaining > 0:
                stop_event.wait(remaining)

    @staticmethod
    def _append_log(log_file: str, payload: dict) -> None:
        with open(log_file, "a", encoding="utf-8") as log:
            log.write(json.dumps(payload) + "\n")

