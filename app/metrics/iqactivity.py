"""Uses the filesystem to track various metrics about image-query activity. Tracks iqs, escalations,
and audits for each detector, as well as iqs submitted to the edge-endpoint as a whole.

Filesystem structure:
/opt/groundlight/edge-metrics/
    detectors/
        <detector_id1>/
            iqs
            iqs_YYYY-MM-DD_HH   <--- Current hour
            iqs_YYYY-MM-DD_HH   <--- Previous hour
            iqs_YYYY-MM-DD_HH   <--- 2 hours ago
            escalations
            escalations_YYYY-MM-DD_HH   <--- Current hour
            escalations_YYYY-MM-DD_HH   <--- Previous hour
            escalations_YYYY-MM-DD_HH   <--- 2 hours ago
            audits
            audits_YYYY-MM-DD_HH   <--- Current hour
            audits_YYYY-MM-DD_HH   <--- Previous hour
            audits_YYYY-MM-DD_HH   <--- 2 hours ago
        <detector_id2>/
            repeat of above detector
    iqs
    iqs_YYYY-MM-DD_HH   <--- Current hour
    iqs_YYYY-MM-DD_HH   <--- Previous hour
    iqs_YYYY-MM-DD_HH   <--- 2 hours ago
"""

import logging
import os
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


class FilesystemActivityTrackingHelper:
    """Helper class to support tracking image-query activity using the filesystem.
    This is just a skeleton and only supports timestamps right now.  But
    we will expand this to support counting metrics, etc."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        # Ensure the base directory exists
        os.makedirs(self.base_dir, exist_ok=True)
        # Ensure the detectors directory exists
        os.makedirs(Path(self.base_dir, "detectors"), exist_ok=True)

    def file(self, name: str) -> Path:
        """Get the path to a file which is used to track something across the whole edge-endpoint (like number of
        active models, or the last image query)"""
        return Path(self.base_dir, name)

    def detector_folder(self, detector_id: str) -> Path:
        """Get the path to the folder for a detector's activity metrics. If it doesn't exist, create it."""
        f = Path(self.base_dir, "detectors", detector_id)
        f.mkdir(parents=True, exist_ok=True)
        return f

    def detector_file(self, detector_id: str, name: str) -> Path:
        """Get the path to a file which is used to track something specific to a detector."""
        return Path(self.detector_folder(detector_id), name)

    def increment_counter_file(self, name: str, detector_id: str | None = None):
        """Increment a counter file, or create it if it doesn't exist. If detector_id is provided,
        use the counter for that detector. Otherwise, use a system-wide counter.

        Args:
            name (str): The name of the counter file.
            detector_id (str | None): The ID of the detector to use, if the counter is for a
                specific detector. If None, use a system-wide counter.
        """
        if detector_id:
            f = self.detector_file(detector_id, name)
        else:
            f = self.file(name)

        if not f.exists():
            f.touch()
            f.write_text("1")
            return

        read_total = int(f.read_text())
        f.write_text(str(read_total + 1))

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


def record_activity(detector_id: str, activity_type: str):
    """Records an activity from a detector. Currently supported activity types are:
    - iqs
    - escalations
    - audits
    """
    supported_activity_types = ["iqs", "escalations", "audits"]
    if activity_type not in supported_activity_types:
        logger.error(
            f"The provided activity type ({activity_type}) is not currently supported, not recording activity. Supported types are: {supported_activity_types}"
        )
        return

    logger.debug(f"Recording activity {activity_type} on detector {detector_id}")

    current_hour = datetime.now().strftime("%Y-%m-%d_%H")
    _tracker().increment_counter_file(activity_type, detector_id)
    _tracker().increment_counter_file(f"{activity_type}_{current_hour}", detector_id)

    # Record IQs for the edge-endpoint as a whole in addition to the detector level, for a quick activity view
    if activity_type == "iqs":
        # Record the time of the last IQ, included since this file was used in the first version of EE metrics
        f = _tracker().file("last_iq")
        f.touch()

        _tracker().increment_counter_file(activity_type)
        _tracker().increment_counter_file(f"{activity_type}_{current_hour}")


def last_activity_time() -> str:
    """Get the last time an image was processed as an ISO 8601 timestamp."""
    last_file_activity = _tracker().get_last_file_activity("iqs")
    return last_file_activity.isoformat() if last_file_activity else "none"


def num_detectors_lifetime() -> int:
    """Get the total number of detectors."""
    f = _tracker().file("detectors")
    return len(list(f.iterdir()))


def num_detectors_active(time_period: timedelta) -> int:
    """Get the number of detectors that have had an IQ submitted to them in the last time period."""
    f = _tracker().file("detectors")
    active_detectors = [
        Path(det, "iqs")
        for det in f.iterdir()
        if _tracker().get_last_file_activity(Path(det, "iqs")) > datetime.now() - time_period
    ]
    return len(active_detectors)


def get_all_detector_activity() -> dict:
    """Get all activity metrics for all detectors."""
    f = _tracker().file("detectors")
    return {det.name: get_detector_activity_metrics(det.name) for det in f.iterdir()}


def get_detector_activity_metrics(detector_id: str) -> dict:
    """Get all activity metrics for a single detector. Note that the "last_hour" metrics are lagging
    -- they return the activity from the previous full hour, not over a sliding window."""
    current_hour = datetime.now().strftime("%Y-%m-%d_%H")
    last_hour = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d_%H")

    detector_metrics = {}

    for activity_type in ["iqs", "escalations", "audits"]:
        f = _tracker().detector_file(detector_id, activity_type)
        last_activity = _tracker().get_last_file_activity(f)
        last_activity = last_activity.isoformat() if last_activity else "none"
        total_activity = int(f.read_text()) if f.exists() else 0

        f = _tracker().detector_file(detector_id, f"{activity_type}_{current_hour}")
        current_hour_activity = int(f.read_text()) if f.exists() else "none"
        f = _tracker().detector_file(detector_id, f"{activity_type}_{last_hour}")
        last_hour_activity = int(f.read_text()) if f.exists() else "none"

        detector_metrics[f"last_{activity_type}"] = last_activity
        detector_metrics[f"total_{activity_type}"] = total_activity
        detector_metrics[f"current_hour_{activity_type}"] = current_hour_activity
        detector_metrics[f"last_hour_{activity_type}"] = last_hour_activity

    return detector_metrics


def clear_old_activity_files():
    """Clear all activity files that are older than 2 hours."""
    base_dir = _tracker().base_dir

    current_hour = datetime.now().strftime("%Y-%m-%d_%H")
    last_hour = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d_%H")
    two_hours_ago = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d_%H")
    valid_hours = [current_hour, last_hour, two_hours_ago]

    # Looking for files that match the pattern <record_name>_YYYY-MM-DD_HH
    time_pattern = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9]"

    folders = list(Path(base_dir, "detectors").iterdir())
    folders.append(base_dir)

    old_files = []
    for folder in folders:
        files = folder.glob(f"*_{time_pattern}")
        old_files.extend([f for f in files if f.name[-len("YYYY-MM-DD_HH") :] not in valid_hours])
    
    if old_files:
        logger.info(f"Clearing {len(old_files)} old activity files: {old_files}")
        for f in old_files:
            f.unlink()
