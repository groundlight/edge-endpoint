"""Tracks image-query activity.
Uses the filesystem to track the last time an image was processed.
"""
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

class FilesystemActivityTracker:
    """Tracks image-query activity using the filesystem.
    """

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        # Ensure the base directory exists
        os.makedirs(self.base_dir, exist_ok=True)

    def file(self, name:str) -> Path:
        """Get the path to the file for a given detector."""
        return Path(self.base_dir, name)

@lru_cache(maxsize=1)  # Singleton
def _tracker() -> FilesystemActivityTracker:
    """Get the activity tracker.
    """
    return FilesystemActivityTracker(base_dir="/opt/groundlight/edge-metrics")

def record_iq_activity(detector_id: str):
    """Currently just records that something happened.
    """
    # TODO: Lots of obvious improvements here.  Number of active detectors,
    # how many images were processed, etc etc.
    f = _tracker().file("last_iq")
    f.touch()

def last_activity_time() -> str:
    """Get the last time an image was processed as an ISO 8601 timestamp."""
    f = _tracker().file("last_iq")
    if not f.exists():
        return "none"
    return datetime.fromtimestamp(f.stat().st_mtime).isoformat()

