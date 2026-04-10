import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from app.profiling.models import Trace

logger = logging.getLogger(__name__)

PROFILING_BASE_DIR = "/opt/groundlight/device/edge-profiling"
ROTATION_INTERVAL_SECONDS = 300  # 5 minutes
MAX_FILE_AGE_HOURS = 24


class ProfilingManager:
    """Manages trace storage. Singleton."""

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

            with open(self._current_file, "a") as f:
                f.write(line)

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
                logger.error(f"Failed to clean up profiling trace file: {f}")
        return deleted
