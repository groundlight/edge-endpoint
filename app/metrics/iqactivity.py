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
    last_iq
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


def record_iq_activity(detector_id: str):
    """Records metrics about image queries submitted to the edge.

    Currently records
     - time of last IQ submission (for the edge-endpoint generally and this detector)
     - total number of IQs processed (for the edge-endpoint generally and this detector)
    """
    current_hour = datetime.now().strftime("%Y-%m-%d_%H")

    # Record the time of the last IQ
    f = _tracker().file("last_iq")
    f.touch()

    # Log iqs processed across the whole edge-endpoint
    _tracker().increment_counter_file("iqs")
    _tracker().increment_counter_file(f"iqs_{current_hour}")

    # Log iqs processed for this detector
    _tracker().increment_counter_file("iqs", detector_id)
    _tracker().increment_counter_file(f"iqs_{current_hour}", detector_id)


def record_escalation(detector_id: str):
    """Records an escalation from a detector."""
    current_hour = datetime.now().strftime("%Y-%m-%d_%H")
    _tracker().increment_counter_file("escalations", detector_id)
    _tracker().increment_counter_file(f"escalations_{current_hour}", detector_id)


def record_audit(detector_id: str):
    """Records an audit from a detector."""
    current_hour = datetime.now().strftime("%Y-%m-%d_%H")
    _tracker().increment_counter_file("audits", detector_id)
    _tracker().increment_counter_file(f"audits_{current_hour}", detector_id)


def last_activity_time() -> str:
    """Get the last time an image was processed as an ISO 8601 timestamp."""
    last_file_activity = _tracker().get_last_file_activity("last_iq")
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

    f = _tracker().detector_file(detector_id, "iqs")
    last_iq = _tracker().get_last_file_activity(f)
    last_iq = last_iq.isoformat() if last_iq else "none"
    total_iqs = int(f.read_text()) if f.exists() else 0

    f = _tracker().detector_file(detector_id, f"iqs_{current_hour}")
    current_hour_iqs = int(f.read_text()) if f.exists() else "none"
    f = _tracker().detector_file(detector_id, f"iqs_{last_hour}")
    last_hour_iqs = int(f.read_text()) if f.exists() else "none"

    f = _tracker().detector_file(detector_id, "escalations")
    last_escalation = _tracker().get_last_file_activity(f)
    last_escalation = last_escalation.isoformat() if last_escalation else "none"
    total_escalations = int(f.read_text()) if f.exists() else 0

    f = _tracker().detector_file(detector_id, f"escalations_{current_hour}")
    current_hour_escalations = int(f.read_text()) if f.exists() else "none"
    f = _tracker().detector_file(detector_id, f"escalations_{last_hour}")
    last_hour_escalations = int(f.read_text()) if f.exists() else "none"

    f = _tracker().detector_file(detector_id, "audits")
    last_audit = _tracker().get_last_file_activity(f)
    last_audit = last_audit.isoformat() if last_audit else "none"
    total_audits = int(f.read_text()) if f.exists() else 0

    f = _tracker().detector_file(detector_id, f"audits_{current_hour}")
    current_hour_audits = int(f.read_text()) if f.exists() else "none"
    f = _tracker().detector_file(detector_id, f"audits_{last_hour}")
    last_hour_audits = int(f.read_text()) if f.exists() else "none"

    return {
        "last_iq": last_iq,
        "last_escalation": last_escalation,
        "last_audit": last_audit,
        "total_iqs": total_iqs,
        "total_escalations": total_escalations,
        "total_audits": total_audits,
        "last_hour_iqs": last_hour_iqs,
        "last_hour_escalations": last_hour_escalations,
        "last_hour_audits": last_hour_audits,
        "current_hour_iqs": current_hour_iqs,
        "current_hour_escalations": current_hour_escalations,
        "current_hour_audits": current_hour_audits,
    }

def clear_old_activity_files_one_folder(folder: Path):
    """Keep the most recent 3 hours of activity files, delete anything older."""
    current_hour = datetime.now().strftime("%Y-%m-%d_%H")
    last_hour = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d_%H")
    two_hours_ago = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d_%H")
    valid_hours = [current_hour, last_hour, two_hours_ago]

    # Files that match the pattern <record_name>_YYYY-MM-DD_HH
    time_pattern = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9]"
    files = folder.glob(f"*_{time_pattern}")

    old_files = [f for f in files if f.name[- len("YYYY-MM-DD_HH"):] not in valid_hours]
    for f in old_files:
        f.unlink()

def clear_old_activity_files():
    """Clear all activity files that are older than 2 hours."""
    base_dir = _tracker().base_dir
    clear_old_activity_files_one_folder(base_dir)

    for detector_folder in Path(base_dir, "detectors").iterdir():
        clear_old_activity_files_one_folder(detector_folder)
