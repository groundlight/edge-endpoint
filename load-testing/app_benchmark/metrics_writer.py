"""Drains sample_queue and frame_queue from background threads in the main process.

Writes:
  - SystemSample → metrics.csv (post-warmup) or warmup.csv (during warmup)
  - FrameEvent   → lens_events.parquet (or .csv fallback if pyarrow not available)
"""

import csv
import logging
import multiprocessing as mp
import queue
import threading
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path

from app_benchmark.ipc import ClientFailedEvent, FrameEvent, GpuDeviceSample, SystemSample

logger = logging.getLogger(__name__)

_FRAME_FLUSH_BATCH = 5000
_QUEUE_TIMEOUT = 0.25


def _gpu_devices_to_str(devices: list[GpuDeviceSample]) -> str:
    if not devices:
        return ""
    return "|".join(
        f"{d.index}:{d.name}:{d.vram_used_bytes}:{d.vram_total_bytes}:{d.compute_pct:.2f}:{d.memory_bandwidth_pct:.2f}"
        for d in devices
    )


def _system_sample_row(sample: SystemSample) -> dict:
    row = {
        "ts": sample.ts,
        "cpu_total_pct": sample.cpu_total_pct,
        "ram_used_bytes": sample.ram_used_bytes,
        "ram_total_bytes": sample.ram_total_bytes,
        "gpu_compute_total_pct": sample.gpu_compute_total_pct,
        "gpu_vram_used_bytes": sample.gpu_vram_used_bytes,
        "gpu_vram_total_bytes": sample.gpu_vram_total_bytes,
        "loading_detectors_bytes": sample.loading_detectors_bytes,
        "error": sample.error or "",
        "gpu_devices": _gpu_devices_to_str(sample.gpu_devices),
    }
    return row


_SAMPLE_COLUMNS = [
    "ts", "cpu_total_pct", "ram_used_bytes", "ram_total_bytes",
    "gpu_compute_total_pct", "gpu_vram_used_bytes", "gpu_vram_total_bytes",
    "loading_detectors_bytes", "error", "gpu_devices",
]

_FRAME_COLUMNS = [
    "ts", "lens_name", "client_id", "stage_idx", "detector_id",
    "latency_ms", "http_status", "retry_count", "was_terminal",
    "composite_objects_count",
]


class MetricsWriter:
    """Background drainer for sample/frame queues. Owns CSV writers."""

    def __init__(
        self,
        output_dir: Path,
        sample_queue: "mp.Queue",
        frame_queue: "mp.Queue",
        stop_event: threading.Event,
    ) -> None:
        self.output_dir = output_dir
        self.sample_queue = sample_queue
        self.frame_queue = frame_queue
        self.stop_event = stop_event

        self._post_warmup = False
        self._dropped_events = 0
        self._monitor_failures = 0
        self._client_failed_events: list[ClientFailedEvent] = []

        self._warmup_path = output_dir / "warmup.csv"
        self._metrics_path = output_dir / "metrics.csv"
        self._frames_path = output_dir / "lens_events.csv"

        self._sample_recent: deque[tuple[float, SystemSample]] = deque(maxlen=2048)
        self._frame_recent: deque[FrameEvent] = deque(maxlen=200_000)

        self._sample_writer = self._open_csv(self._warmup_path, _SAMPLE_COLUMNS)
        self._metrics_writer = self._open_csv(self._metrics_path, _SAMPLE_COLUMNS)
        self._frame_writer = self._open_csv(self._frames_path, _FRAME_COLUMNS)

        self._sample_thread = threading.Thread(target=self._drain_samples, name="metrics-samples", daemon=True)
        self._frame_thread = threading.Thread(target=self._drain_frames, name="metrics-frames", daemon=True)

    @staticmethod
    def _open_csv(path: Path, columns: list[str]):
        path.parent.mkdir(parents=True, exist_ok=True)
        f = path.open("w", newline="")
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        f.flush()
        return _CsvHandle(file=f, writer=writer)

    def start(self) -> None:
        self._sample_thread.start()
        self._frame_thread.start()

    def stop(self) -> None:
        # The drain threads watch stop_event and exit when both queues are empty.
        self._sample_thread.join(timeout=10.0)
        self._frame_thread.join(timeout=10.0)
        for handle in (self._sample_writer, self._metrics_writer, self._frame_writer):
            handle.close()

    def mark_post_warmup(self) -> None:
        self._post_warmup = True

    def recent_samples(self, last_n_seconds: float) -> list[SystemSample]:
        cutoff = time.time() - last_n_seconds
        return [s for ts, s in self._sample_recent if ts >= cutoff]

    def recent_frame_events(self, last_n_seconds: float) -> list[FrameEvent]:
        cutoff = time.time() - last_n_seconds
        return [e for e in self._frame_recent if e.ts >= cutoff]

    def per_lens_recent_fps(self, last_n_seconds: float = 5.0) -> dict[str, float]:
        events = [e for e in self.recent_frame_events(last_n_seconds) if e.stage_idx == -1]
        if not events:
            return {}
        oldest = min(e.ts for e in events)
        newest = max(e.ts for e in events)
        window = max(0.001, newest - oldest)
        counts: dict[str, int] = {}
        for e in events:
            counts[e.lens_name] = counts.get(e.lens_name, 0) + 1
        return {lens: count / window for lens, count in counts.items()}

    def dropped_events(self) -> int:
        return self._dropped_events

    def monitor_failures(self) -> int:
        return self._monitor_failures

    def client_failed_events(self) -> list[ClientFailedEvent]:
        return list(self._client_failed_events)

    # --- drain loops --------------------------------------------------------

    def _drain_samples(self) -> None:
        while True:
            try:
                sample = self.sample_queue.get(timeout=_QUEUE_TIMEOUT)
            except queue.Empty:
                if self.stop_event.is_set():
                    return
                continue
            if sample.error:
                self._monitor_failures += 1
            self._sample_recent.append((sample.ts, sample))
            row = _system_sample_row(sample)
            handle = self._metrics_writer if self._post_warmup else self._sample_writer
            handle.writerow(row)

    def _drain_frames(self) -> None:
        batch: list[FrameEvent] = []
        last_flush = time.time()
        while True:
            try:
                event = self.frame_queue.get(timeout=_QUEUE_TIMEOUT)
            except queue.Empty:
                if self.stop_event.is_set() and not batch:
                    return
                if batch and time.time() - last_flush > 1.0:
                    self._flush_frames(batch)
                    batch = []
                    last_flush = time.time()
                continue

            if isinstance(event, ClientFailedEvent):
                self._client_failed_events.append(event)
                continue

            if not isinstance(event, FrameEvent):
                continue

            self._frame_recent.append(event)
            batch.append(event)
            if len(batch) >= _FRAME_FLUSH_BATCH:
                self._flush_frames(batch)
                batch = []
                last_flush = time.time()

        # unreachable

    def _flush_frames(self, batch: list[FrameEvent]) -> None:
        for e in batch:
            self._frame_writer.writerow({
                "ts": e.ts,
                "lens_name": e.lens_name,
                "client_id": e.client_id,
                "stage_idx": e.stage_idx,
                "detector_id": e.detector_id,
                "latency_ms": e.latency_ms,
                "http_status": e.http_status,
                "retry_count": e.retry_count,
                "was_terminal": int(e.was_terminal),
                "composite_objects_count": e.composite_objects_count,
            })


class _CsvHandle:
    def __init__(self, file, writer: csv.DictWriter) -> None:
        self.file = file
        self.writer = writer

    def writerow(self, row: dict) -> None:
        self.writer.writerow(row)
        self.file.flush()

    def close(self) -> None:
        try:
            self.file.flush()
            self.file.close()
        except Exception:
            pass
