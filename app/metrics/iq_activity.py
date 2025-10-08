"""Uses the filesystem to track various metrics about image-query activity. Tracks iqs, escalations,
and audits for each detector, as well as iqs submitted to the edge-endpoint as a whole.

Filesystem structure:
/opt/groundlight/edge-metrics/
    detectors/
        <detector_id1>/
            last_iqs
            last_escalations
            last_audits
            iqs_<pid1>_YYYY-MM-DD_HH    <-- arbitrary number of files, one per process. hourly files cleared out regularly
            iqs_<pid1>_YYYY-MM-DD_HH
            iqs_<pid2>_YYYY-MM-DD_HH
            iqs_<pid2>_YYYY-MM-DD_HH
            escalations_<pid1>_YYYY-MM-DD_HH
            escalations_<pid2>_YYYY-MM-DD_HH
            audits_<pid1>_YYYY-MM-DD_HH
        <detector_id2>/
            repeat of above detector
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
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
        """Get the path to a file which is used to track the last time "activity_type" occurred, on
        a per-detector or system-wide basis. Not specific to a process.
        """
        name = f"last_{activity_type}"

        if detector_id:
            return self.detector_file(detector_id, name)

        return self.file(name)

    def hourly_activity_file(self, activity_type: str, time: datetime, detector_id: str | None = None) -> Path:
        """Get the path to a file which is used to track the number of times an activity type
        occurred in an hour on this process."""
        hour = time.strftime("%Y-%m-%d_%H")
        pid = os.getpid()

        name = f"{activity_type}_{pid}_{hour}"

        if detector_id:
            return self.detector_file(detector_id, name)

        return self.file(name)

    def increment_counter_file(self, file: Path):
        """Increment a counter file, or create it if it doesn't exist.

        Args:
            file (Path): The path to the counter file.
        """
        if not file.exists():
            file.touch()
            file.write_text("1")
            return

        read_total = int(file.read_text())
        file.write_text(str(read_total + 1))

    def get_last_file_modification_time(self, file: Path) -> datetime | None:
        """Get the last time a file was modified."""
        if not file.exists():
            return None
        return datetime.fromtimestamp(file.stat().st_mtime)

    def get_activity_from_file(self, file: Path) -> int:
        """Get the activity from a file. Returns 0 if the file doesn't exist or is empty."""
        if not file.exists():
            return 0

        text = file.read_text(encoding="utf-8")
        if text == "":
            return 0
        return int(text)


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
        activity_files = [_tracker().last_activity_file("iqs", det.name) for det in f.iterdir()]
        active_detectors = [
            file.parent.name
            for file in activity_files
            if _tracker().get_last_file_modification_time(file) > datetime.now() - time_period
        ]
        return len(active_detectors)

    def get_all_detector_activity(self) -> dict:
        """Get all activity metrics for all detectors."""
        f = _tracker().detectors_dir
        detector_activity = {det.name: self.get_detector_activity_metrics(det.name) for det in f.iterdir()}
        return detector_activity

    def get_active_detector_activity(self) -> str:
        """Get activity metrics for detectors that have had iqs submitted in the last hour."""
        all_detector_activity = self.get_all_detector_activity()
        active_detector_activity = {
            det: data for det, data in all_detector_activity.items() if data["hourly_total_iqs"] > 0
        }
        # Convert the active_detector_activity dict to a JSON string to prevent opensearch from indexing all
        # the individual detector fields
        return json.dumps(active_detector_activity)

    def get_last_hour(self) -> str:
        """Get the last hour in UTC."""
        return (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d_%H")

    def get_detector_activity_metrics(self, detector_id: str) -> int:
        """Get the activity on a detector for the previous hour."""
        time = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d_%H")
        logger.info(f"Getting activity for detector {detector_id} at {time}")

        detector_folder = _tracker().detector_folder(detector_id)
        activity_files = list(detector_folder.glob(f"*_{time}"))

        detector_metrics = {}
        for activity_type in ["iqs", "escalations", "audits"]:
            files = [f for f in activity_files if f.name.startswith(activity_type)]
            total_activity = sum([_tracker().get_activity_from_file(f) for f in files])
            f = _tracker().last_activity_file(activity_type, detector_id)
            last_activity = _tracker().get_last_file_modification_time(f)
            last_activity = last_activity.isoformat() if last_activity else "none"

            detector_metrics[f"hourly_total_{activity_type}"] = total_activity
            detector_metrics[f"last_{activity_type[:-1]}"] = last_activity

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
    _tracker().increment_counter_file(f)

    f = _tracker().last_activity_file(activity_type, detector_id)
    f.touch()


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

    if old_files:
        logger.info(f"Clearing {len(old_files)} old activity files: {old_files}")
        for f in old_files:
            f.unlink()
