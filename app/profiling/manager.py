import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from math import sqrt
from pathlib import Path

from app.profiling.models import Trace

logger = logging.getLogger(__name__)

PROFILING_BASE_DIR = "/opt/groundlight/device/edge-profiling"
ROTATION_INTERVAL_SECONDS = 300  # 5 minutes
MAX_FILE_AGE_HOURS = 24


class ProfilingManager:
    """Manages trace storage and aggregation. Singleton."""

    def __init__(self, base_dir: str = PROFILING_BASE_DIR):
        self.base_dir = Path(base_dir)
        self.traces_dir = self.base_dir / "traces"
        os.makedirs(self.traces_dir, exist_ok=True)

        self._write_lock = threading.Lock()
        self._current_file: Path | None = None
        self._current_file_created_at: float = 0

    def record_trace(self, trace: Trace) -> None:
        """Append a completed trace as a single JSONL line."""
        line = json.dumps(trace.to_dict(), separators=(",", ":")) + "\n"

        with self._write_lock:
            now = time.monotonic()
            if self._current_file is None or (now - self._current_file_created_at) >= ROTATION_INTERVAL_SECONDS:
                self._rotate_file(now)

            try:
                with open(self._current_file, "a") as f:
                    f.write(line)
            except OSError:
                logger.warning(f"Failed to write profiling trace to {self._current_file}")

    def _rotate_file(self, now: float) -> None:
        """Create a new trace file. Must be called under _write_lock."""
        pid = os.getpid()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
        filename = f"traces_{pid}_{ts}.jsonl"
        self._current_file = self.traces_dir / filename
        self._current_file_created_at = now

    def cleanup_old_files(self) -> int:
        """Remove trace files older than MAX_FILE_AGE_HOURS. Returns count deleted."""
        cutoff = time.time() - (MAX_FILE_AGE_HOURS * 3600)
        deleted = 0
        for f in self.traces_dir.glob("traces_*.jsonl"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except OSError:
                logger.warning(f"Failed to clean up profiling trace file: {f}")
        return deleted

    def compute_aggregation(self, detector_id: str | None = None, hours: int = 1) -> dict:
        """Compute per-span-name statistics from stored traces.

        Returns dict keyed by span name, each containing:
          count, mean_ms, stddev_ms, min_ms, max_ms, p50_ms, p90_ms, p99_ms
        """
        cutoff = time.time() - (hours * 3600)
        span_durations: dict[str, list[float]] = defaultdict(list)

        for f in self.traces_dir.glob("traces_*.jsonl"):
            try:
                if f.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            try:
                with open(f, "r") as fh:
                    for line in fh:
                        try:
                            trace_dict = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if detector_id and trace_dict.get("detector_id") != detector_id:
                            continue
                        for span in trace_dict.get("spans", []):
                            span_name = span.get("name")
                            dur = span.get("duration_ms")
                            if span_name is not None and dur is not None and dur >= 0:
                                span_durations[span_name].append(dur)
            except OSError:
                logger.warning(f"Failed to read profiling trace file: {f}")

        result = {}
        for name, durations in span_durations.items():
            durations.sort()
            n = len(durations)
            mean = sum(durations) / n
            # Population variance (divides by n, not n-1) since we're measuring all traces in the window.
            variance = sum((d - mean) ** 2 for d in durations) / n if n > 1 else 0
            result[name] = {
                "count": n,
                "mean_ms": round(mean, 3),
                "stddev_ms": round(sqrt(variance), 3),
                "min_ms": round(durations[0], 3),
                "max_ms": round(durations[-1], 3),
                "p50_ms": round(durations[n // 2], 3),
                "p90_ms": round(durations[int(n * 0.9)], 3),
                "p99_ms": round(durations[int(n * 0.99)], 3),
            }

        return result
