import logging
import os
from pathlib import Path

from app.escalation_queue.constants import DEFAULT_REQUEST_CACHE_DIR, DEFAULT_REQUEST_CACHE_MAX_ENTRIES

from app.utils.loghelper import create_logger

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

logger = create_logger(__name__, component="escalation-queue-reader")

class RequestCache:
    """
    A simple file-based cache for request IDs.
    Each cached request ID is represented as an empty file in the cache directory.
    The cache evicts the oldest entry when the maximum size is exceeded.

    This is used to detect and skip duplicate escalations in the queue, which can arise from the way the Groundlight SDK
    does retries for failed requests. If we implement a different way of preventing retries on the edge in the future,
    this can be removed.
    """

    def __init__(
        self, cache_dir: str = DEFAULT_REQUEST_CACHE_DIR, max_entries: int = DEFAULT_REQUEST_CACHE_MAX_ENTRIES
    ) -> None:
        """
        Initialize the cache.

        Args:
            cache_dir: Path to the cache directory.
            max_entries: Maximum number of entries to store.
        """
        self.cache_dir = Path(cache_dir)
        self.max_entries = max_entries
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"Initialized a RequestCache at {self.cache_dir.resolve()} with {self.max_entries} max entries.")

    def _entry_path(self, request_id: str) -> Path:
        return self.cache_dir / request_id

    def _all_entries(self) -> list[Path]:
        return [f for f in self.cache_dir.iterdir() if f.is_file()]

    def _oldest_entries(self, n: int) -> list[Path]:
        entries = self._all_entries()
        # Use modification time (mtime) in nanoseconds for ordering. Two files may have equivalent mtime_ns values if
        # created in succession, due to varying time resolution between operating systems and file systems. In practice,
        # we're okay with a rough ordering of the oldest entries.
        return sorted(entries, key=lambda f: f.stat().st_mtime_ns)[:n]

    def add(self, request_id: str) -> None:
        """
        Add a request ID to the cache, evicting oldest if necessary.
        """
        entry = self._entry_path(request_id)
        if entry.exists():
            return  # Already cached

        entries = self._all_entries()
        if len(entries) >= self.max_entries:
            # Remove oldest entries to make space for the new one
            num_to_remove = len(entries) - self.max_entries + 1
            logger.debug(
                f"Removing the {num_to_remove} oldest item(s) from the request cache to make room for a new entry."
            )
            for old_entry in self._oldest_entries(num_to_remove):
                try:
                    old_entry.unlink()
                except FileNotFoundError:
                    pass  # Ignore if already deleted

        # Add the new entry
        entry.touch(exist_ok=True)
        logger.debug(f"Added {request_id} to the request cache.")

    def contains(self, request_id: str) -> bool:
        """
        Check if a request ID is in the cache.
        """
        return self._entry_path(request_id).exists()
