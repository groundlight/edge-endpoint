"""Tracks image-query activity.
Uses the filesystem to track the last time an image was processed.

Filesystem structure:
/opt/groundlight/edge-metrics/
    detectors/
        <detector_id1>/
            last_iq
        <detector_id2>/
            last_iq
    last_iq
"""

import os
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path


class FilesystemActivityTrackingHelper:
    """Helper class to support tracking image-query activity using the filesystem.
    This is just a skeleton and only supports timestamps right now.  But
    we will expand this to support counting metrics, etc."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        # Ensure the base directory exists
        os.makedirs(self.base_dir, exist_ok=True)

    def file(self, name: str) -> Path:
        """Get the path to a file which is used to track something.  Could be specific to a detector,
        or something system-wide like number of active models, or the last image query."""
        return Path(self.base_dir, name)

    def get_last_file_activity(self, name: str) -> datetime | None:
        """Get the last time a file was modified."""
        f = self.file(name)
        if not f.exists():
            return None
        return datetime.fromtimestamp(f.stat().st_mtime)


@lru_cache(maxsize=1)  # Singleton
def _tracker() -> FilesystemActivityTrackingHelper:
    """Get the activity tracker."""
    return FilesystemActivityTrackingHelper(base_dir="/opt/groundlight/device/edge-metrics")


def record_iq_activity(detector_id: str):
    """Currently just records that something happened on the detector."""
    # TODO: Lots of obvious improvements here.  Number of active detectors,
    # how many images were processed, etc etc.

    # Record the time of the last IQ (in general)
    f = _tracker().file("last_iq")
    f.touch()
    
    record_detector_activity(detector_id)


def record_detector_activity(detector_id: str):
    """Records the time of the last IQ for a detector."""
    f = _tracker().file(Path("detectors", detector_id, "last_iq"))
    f.touch()


def last_activity_time() -> str:
    """Get the last time an image was processed as an ISO 8601 timestamp."""
    last_file_activity = _tracker().get_last_file_activity("last_iq")
    return last_file_activity.isoformat() if last_file_activity else "none"


def num_detectors_lifetime() -> int:
    """Get the total number of detectors."""
    f = _tracker().file("detectors")
    return len(list(f.iterdir()))


def num_detectors_active() -> int:
    """Get the number of detectors that have had an IQ submitted to them in the last hour."""
    f = _tracker().file("detectors")
    active_detectors = [Path(det, "last_iq") for det in f.iterdir() if _tracker().get_last_file_activity(Path(det, "last_iq")) > datetime.now() - timedelta(hours=1)]
    return len(active_detectors)
