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
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


class FilesystemActivityTrackingHelper:
    """Helper class to support tracking image-query activity using the filesystem."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        # Ensure the base directory exists
        os.makedirs(self.base_dir, exist_ok=True)

        self.detectors_dir = Path(self.base_dir, "detectors")
        # Ensure the detectors directory exists
        os.makedirs(self.detectors_dir, exist_ok=True)

    def file(self, name: str) -> Path:
        """Get the path to a file which is used to track something across the whole edge-endpoint (like number of
        active models, or the last image query)"""
        return Path(self.base_dir, name)

    def detector_folder(self, detector_id: str) -> Path:
        """Get the path to the folder for a detector's activity metrics. If it doesn't exist, create it."""
        f = Path(self.detectors_dir, detector_id)
        f.mkdir(parents=True, exist_ok=True)
        return f

    def detector_file(self, detector_id: str, name: str) -> Path:
        """Get the path to a file which is used to track something specific to a detector."""
        return Path(self.detector_folder(detector_id), name)

    def last_activity_file(self, activity_type: str, detector_id: str | None = None) -> Path:
        """Get the path to a file which is used to track the last time an image was processed by the edge-endpoint."""
        name = f"last_{activity_type}"

        if detector_id:
            return self.detector_file(detector_id, name)
        
        return self.file(name)

    def hourly_activity_file(self, activity_type: str, time: datetime, detector_id: str | None = None) -> Path:
        """Get the path to a file which is used to track the number of times an activity type occurred in an hour."""
        hour = time.strftime("%Y-%m-%d_%H")

        name = f"{activity_type}_{hour}"

        if detector_id:
            return self.detector_file(detector_id, name)

        return self.file(name)

    def append_to_hourly_counter_file(self, file: Path):
        """Append a "." to an hourly counter file, or create it if it doesn't exist. If detector_id
        is provided, use the counter for that detector. Otherwise, use a system-wide counter.

        This is only used for the hourly counters, not the lifetime total counters, so we clear them
        regularly and the files don't become unboundedly large.
        """
        if not file.exists():
            file.touch()

        # open in append mode to avoid race condition
        with file.open("a") as f:
            f.write(".")

    def get_last_file_modification_time(self, file: Path) -> datetime | None:
        """Get the last time a file was modified."""
        if not file.exists():
            return None
        return datetime.fromtimestamp(file.stat().st_mtime)

    def get_file_length(self, name: str) -> int:
        """Get the length of a file's content. Returns 0 if the file doesn't exist."""
        f = self.file(name)
        if not f.exists():
            return 0
        content = f.read_text(encoding='utf-8')
        return len(content)

    def get_activity_from_file(self, name: str) -> int:
        """Get the activity from a file. Returns 0 if the file doesn't exist."""
        f = self.file(name)
        if not f.exists():
            return 0

        # if the file is an hourly counter, return the length of the content
        # Looking for files that match the pattern <record_name>_YYYY-MM-DD_HH
        time_pattern = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9]$"
        if re.search(time_pattern, name):
            return self.get_file_length(name)
        # otherwise, the file is a lifetime counter, so return the content as an int
        return int(f.read_text())

    def update_lifetime_counters_from_hourly_files(self, hourly_files: list[Path]):
        """Update the relevant lifetime counters with the activity from a list of hourly files."""
        for hourly_file in hourly_files:
            # The total file has the same path and activity type as the hourly file, just remove the _YYYY-MM-DD_HH suffix
            folder = hourly_file.parent
            activity_type = hourly_file.name.split("_")[0]
            total_file = Path(folder, activity_type)

            if not total_file.exists():
                total_file.touch()

            prev_total = self.get_activity_from_file(total_file)
            hour_total = self.get_activity_from_file(hourly_file)
            total_file.write_text(str(prev_total + hour_total))


class ActivityRetriever:
    """Retrieve IQ activity metrics from the filesystem to report them."""

    def last_activity_time(self) -> str:
        """Get the last time an image was processed by the edge-endpoint as an ISO 8601 timestamp."""
        activity_file = _tracker().last_activity_file("iqs")
        last_file_activity = _tracker().get_last_file_modification_time(activity_file)
        return last_file_activity.isoformat() if last_file_activity else "none"

    def num_detectors_lifetime(self) -> int:
        """Get the total number of detectors."""
        f = _tracker().detectors_dir
        return len(list(f.iterdir()))

    def num_detectors_active(self, time_period: timedelta) -> int:
        """Get the number of detectors that have had an IQ submitted to them in the last time period."""
        f = _tracker().detectors_dir
        activity_files = [
            _tracker().last_activity_file("iqs", det.name)
            for det in f.iterdir()
        ]
        active_detectors = [
            file.parent.name
            for file in activity_files
            if _tracker().get_last_file_modification_time(file) > datetime.now() - time_period
        ]
        return len(active_detectors)

    def get_all_detector_activity(self) -> dict:
        """Get all activity metrics for all detectors."""
        f = _tracker().detectors_dir
        return {det.name: self.get_detector_activity_metrics(det.name) for det in f.iterdir()}

    def get_detector_activity_metrics(self, detector_id: str) -> dict:
        """Get all activity metrics for a single detector.

        Return info
        * last_<activity_type> -- last time <activity_type> occurred for this detector
        * total_<activity_type> -- total number of <activity_type> for this detector, excluding
            those recorded in hourly activity files (lagging)
        * current_hour_<activity_type> -- number of <activity_type> for this detector in the current
            full hour (not a sliding window)
        * last_hour_<activity_type> -- number of <activity_type> for this detector in the previous
            full hour (not a sliding window)
        """
        current_hour = datetime.now()
        last_hour = current_hour - timedelta(hours=1)

        detector_metrics = {}

        for activity_type in ["iqs", "escalations", "audits"]:
            f = _tracker().last_activity_file(activity_type, detector_id)
            last_activity = _tracker().get_last_file_modification_time(f)
            last_activity = last_activity.isoformat() if last_activity else "none"

            f = _tracker().detector_file(detector_id, activity_type)
            total_activity = _tracker().get_activity_from_file(f)

            f = _tracker().hourly_activity_file(activity_type, current_hour, detector_id)
            current_hour_activity = _tracker().get_activity_from_file(f)
            f = _tracker().hourly_activity_file(activity_type, last_hour, detector_id)
            last_hour_activity = _tracker().get_activity_from_file(f)

            detector_metrics[f"last_{activity_type}"] = last_activity
            detector_metrics[f"total_{activity_type}"] = total_activity
            detector_metrics[f"current_hour_{activity_type}"] = current_hour_activity
            detector_metrics[f"last_hour_{activity_type}"] = last_hour_activity

        return detector_metrics

@lru_cache(maxsize=1)  # Singleton
def _tracker() -> FilesystemActivityTrackingHelper:
    """Get the activity tracker."""
    return FilesystemActivityTrackingHelper(base_dir="/opt/groundlight/device/edge-metrics")


def record_activity_for_metrics(detector_id: str, activity_type: str):
    """Records an activity from a detector. Currently supported activity types are:
    - iqs
    - escalations
    - audits
    """
    supported_activity_types = ["iqs", "escalations", "audits"]
    if activity_type not in supported_activity_types:
        raise ValueError(
            f"The provided activity type ({activity_type}) is not currently supported. Supported types are: {supported_activity_types}"
        )

    logger.debug(f"Recording activity {activity_type} on detector {detector_id}")

    current_hour = datetime.now()
    f = _tracker().hourly_activity_file(activity_type, current_hour, detector_id)
    _tracker().append_to_hourly_counter_file(f)

    # record last activity time
    f = _tracker().last_activity_file(activity_type, detector_id)
    f.touch()

    # Record IQs for the edge-endpoint as a whole in addition to the detector level, for a quick activity view
    if activity_type == "iqs":
        f = _tracker().last_activity_file("iqs")
        f.touch()

        f = _tracker().hourly_activity_file("iqs", current_hour)
        _tracker().append_to_hourly_counter_file(f)


def clear_old_activity_files():
    """Clear all activity files that are older than 2 hours."""
    current_hour = datetime.now().strftime("%Y-%m-%d_%H")
    last_hour = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d_%H")
    two_hours_ago = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d_%H")
    valid_hours = [current_hour, last_hour, two_hours_ago]

    # Looking for files that match the pattern <record_name>_YYYY-MM-DD_HH
    time_pattern = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9]"

    folders = list(_tracker().detectors_dir.iterdir())
    folders.append(_tracker().base_dir)

    old_files = []
    for folder in folders:
        files = folder.glob(f"*_{time_pattern}")
        old_files.extend([f for f in files if f.name[-len("YYYY-MM-DD_HH") :] not in valid_hours])

    _tracker().update_lifetime_counters_from_hourly_files(old_files)

    if old_files:
        logger.info(f"Clearing {len(old_files)} old activity files: {old_files}")
        for f in old_files:
            f.unlink()
