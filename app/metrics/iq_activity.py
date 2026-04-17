"""Uses the filesystem to track various metrics about image-query activity. Tracks iqs, escalations,
audits, below_threshold_iqs, and confidence histograms for each detector, as well as iqs submitted to the
edge-endpoint as a whole.

Filesystem structure:
/opt/groundlight/device/edge-metrics/
    detectors/
        <detector_id1>/
            last_iqs
            last_escalations
            last_audits
            last_below_threshold_iqs
            iqs_<pid1>_YYYY-MM-DD_HH    <-- arbitrary number of files, one per process. hourly files cleared out regularly
            iqs_<pid1>_YYYY-MM-DD_HH
            iqs_<pid2>_YYYY-MM-DD_HH
            iqs_<pid2>_YYYY-MM-DD_HH
            escalations_<pid1>_YYYY-MM-DD_HH
            escalations_<pid2>_YYYY-MM-DD_HH
            audits_<pid1>_YYYY-MM-DD_HH
            below_threshold_iqs_<pid1>_YYYY-MM-DD_HH
            confidence_v2_0-5_<pid1>_YYYY-MM-DD_HH    <-- confidence histogram buckets (5% intervals, version-prefixed)
            confidence_v2_95-100_<pid1>_YYYY-MM-DD_HH
            confidence_v2_class_0_70-75_<pid1>_YYYY-MM-DD_HH    <-- per-class confidence histograms
            escalations_class_0_<pid1>_YYYY-MM-DD_HH          <-- per-class activity counters
            below_threshold_iqs_class_0_<pid1>_YYYY-MM-DD_HH
        <detector_id2>/
            repeat of above detector
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from app.profiling.context import trace_span

logger = logging.getLogger(__name__)

PER_CLASS_ACTIVITY_TYPES = ["escalations", "below_threshold_iqs"]


class ConfidenceHistogramConfig:
    """Confidence histogram parameters and logic.

    If BUCKET_WIDTH is changed, VERSION must be bumped so the read path
    can distinguish old-width files on disk and skip them.  BUCKET_WIDTH
    should evenly divide 100.

    VERSION history:
    - v1: Aggregate only, 5% bucket width, 20 buckets. Envelope: {"counts": [...]}
    - v2: Per-class support added (same bucket structure). Envelope adds "by_class"
          key alongside "counts". Read path accepts v1 aggregate files on disk.
    """

    VERSION = 2
    BUCKET_WIDTH = 5
    NUM_BUCKETS = 100 // BUCKET_WIDTH

    @staticmethod
    def filename_prefix(class_index: int | None = None) -> str:
        """Prefix for current-version confidence files on disk.

        Args:
            class_index: If provided, returns prefix for per-class file.
                        If None, returns prefix for aggregate file.
        """
        if class_index is None:
            return f"confidence_v{ConfidenceHistogramConfig.VERSION}"
        return f"confidence_v{ConfidenceHistogramConfig.VERSION}_class_{class_index}"

    @staticmethod
    def confidence_to_bucket(confidence: float) -> str:
        """Convert confidence (0.0-1.0) to bucket name like '70-75'."""
        w = ConfidenceHistogramConfig.BUCKET_WIDTH
        if confidence == 1.0:
            return f"{100 - w}-100"
        bucket_start = int(confidence * 100) // w * w
        return f"{bucket_start}-{bucket_start + w}"

    @staticmethod
    def bucket_name_to_index(bucket: str) -> int:
        """Convert bucket name like '70-75' to array index. Raises ValueError if invalid."""
        try:
            parts = bucket.split("-")
            bucket_start = int(parts[0])
            bucket_end = int(parts[1])
        except (ValueError, IndexError):
            raise ValueError(f"Malformed confidence bucket name: {bucket}")
        if bucket_end - bucket_start != ConfidenceHistogramConfig.BUCKET_WIDTH:
            raise ValueError(f"Confidence bucket width mismatch: {bucket}")
        index = bucket_start // ConfidenceHistogramConfig.BUCKET_WIDTH
        if not (0 <= index < ConfidenceHistogramConfig.NUM_BUCKETS):
            raise ValueError(f"Confidence bucket index out of range: {bucket}")
        return index

    @staticmethod
    def empty_counts() -> list[int]:
        return [0] * ConfidenceHistogramConfig.NUM_BUCKETS

    @staticmethod
    def to_envelope(aggregate_counts: list[int], by_class_counts: dict[str, list[int]] | None = None) -> dict:
        cfg = ConfidenceHistogramConfig
        envelope = {
            "version": cfg.VERSION,
            "bucket_width": cfg.BUCKET_WIDTH,
            "counts": aggregate_counts,
            "by_class": by_class_counts or {},
        }
        return envelope


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

    @staticmethod
    def _previous_hour_local() -> str:
        """Get the previous hour as a local-time string matching hourly activity filenames."""
        return (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d_%H")

    def last_activity_time(self) -> str | None:
        """Get the last time an image was processed by the edge-endpoint as an ISO 8601 timestamp."""
        activity_file = _tracker().last_activity_file("iqs")
        last_file_activity = _tracker().get_last_file_modification_time(activity_file)
        return last_file_activity.isoformat() if last_file_activity else None

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

    @staticmethod
    def get_last_hour() -> str:
        """Get the last hour in UTC."""
        return (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d_%H")

    def get_per_class_activity(self, detector_id: str, activity_type: str, hourly_files: list[Path]) -> dict[str, int]:
        """Get per-class counts for an activity type for the previous hour.

        Args:
            detector_id: The detector ID.
            activity_type: "below_threshold_iqs" or "escalations".
            hourly_files: Pre-fetched list of hourly files to filter from.

        Returns:
            Dict mapping class index strings to counts.
        """
        prefix = f"{activity_type}_class_"
        activity_files = [f for f in hourly_files if f.name.startswith(prefix)]

        by_class: dict[str, int] = {}

        for f in activity_files:
            # Remainder is "<index>_<pid>_YYYY-MM-DD_HH"
            remainder = f.name[len(prefix) :]
            class_index = remainder.split("_")[0]
            count = _tracker().get_activity_from_file(f)
            by_class[class_index] = by_class.get(class_index, 0) + count

        return by_class

    def get_detector_confidence_histogram(self, detector_id: str) -> dict:
        """Get the confidence histogram for a detector for the previous hour.

        Globs for all versioned confidence files (``confidence_v*_…``).
        Files from any version are accepted; bucket_name_to_index validates
        the bucket width matches, so files from a version with a different
        bucket width are safely skipped.

        Returns:
            A versioned, self-describing envelope with aggregate and per-class data:
            {
                "version": 2,
                "bucket_width": 5,
                "counts": [10, 25, ...],  # 20 elements, one per 5% bucket
                "by_class": {
                    "0": [5, 10, ...],
                    "1": [5, 15, ...]
                }
            }
            The i-th element of counts is the count for [i*bucket_width, (i+1)*bucket_width).
        """
        cfg = ConfidenceHistogramConfig
        time = self._previous_hour_local()
        detector_folder = _tracker().detector_folder(detector_id)
        activity_files = list(detector_folder.glob(f"confidence_v*_*_{time}"))

        aggregate_counts = cfg.empty_counts()
        by_class_counts: dict[str, list[int]] = {}

        for f in activity_files:
            # Filename formats:
            # - Aggregate: "confidence_v<version>_<bucket>_<pid>_YYYY-MM-DD_HH"
            # - Per-class: "confidence_v<version>_class_<index>_<bucket>_<pid>_YYYY-MM-DD_HH"
            parts = f.name.split("_")

            # Check if this is a per-class file
            if parts[2] == "class":
                # Per-class file: confidence_v2_class_<index>_<bucket>_<pid>_YYYY-MM-DD_HH
                class_index = parts[3]
                bucket = parts[4]

                try:
                    index = cfg.bucket_name_to_index(bucket)
                except ValueError:
                    logger.error(f"Skipping confidence file with invalid bucket: {f.name}")
                    continue

                if class_index not in by_class_counts:
                    by_class_counts[class_index] = cfg.empty_counts()

                count = _tracker().get_activity_from_file(f)
                by_class_counts[class_index][index] += count
            else:
                # Aggregate file: confidence_v2_<bucket>_<pid>_YYYY-MM-DD_HH
                bucket = parts[2]

                try:
                    index = cfg.bucket_name_to_index(bucket)
                except ValueError:
                    logger.error(f"Skipping confidence file with invalid bucket: {f.name}")
                    continue

                count = _tracker().get_activity_from_file(f)
                aggregate_counts[index] += count

        return cfg.to_envelope(aggregate_counts, by_class_counts)

    def get_detector_activity_metrics(self, detector_id: str) -> dict:
        """Get the activity on a detector for the previous hour."""
        time = self._previous_hour_local()
        logger.info(f"Getting activity for detector {detector_id} at {time}")

        detector_folder = _tracker().detector_folder(detector_id)
        activity_files = list(detector_folder.glob(f"*_{time}"))

        detector_metrics = {}

        for activity_type in ["iqs", "escalations", "audits", "below_threshold_iqs"]:
            # Get aggregate files (exclude per-class files which contain "_class_")
            files = [f for f in activity_files if f.name.startswith(activity_type) and "_class_" not in f.name]
            total_activity = sum([_tracker().get_activity_from_file(f) for f in files])
            f = _tracker().last_activity_file(activity_type, detector_id)
            last_activity = _tracker().get_last_file_modification_time(f)
            last_activity = last_activity.isoformat() if last_activity else None

            detector_metrics[f"hourly_total_{activity_type}"] = total_activity
            detector_metrics[f"last_{activity_type[:-1]}"] = last_activity

            # Add per-class breakdown for supported activity types
            if activity_type in PER_CLASS_ACTIVITY_TYPES:
                by_class = self.get_per_class_activity(detector_id, activity_type, hourly_files=activity_files)
                if by_class:
                    detector_metrics[f"{activity_type}_by_class"] = by_class

        # Add confidence histogram
        detector_metrics["confidence_histogram"] = self.get_detector_confidence_histogram(detector_id)

        return detector_metrics


@lru_cache(maxsize=1)  # Singleton
def _tracker() -> FilesystemActivityTrackingHelper:
    """Get the activity tracker."""
    return FilesystemActivityTrackingHelper(base_dir="/opt/groundlight/device/edge-metrics")


@trace_span
def record_activity_for_metrics(detector_id: str, activity_type: str, class_index: int | None = None):
    """Records an activity from a detector.

    Supported activity types:
    - iqs: Total image queries
    - escalations: Escalations to cloud (per-class supported)
    - audits: Audit submissions
    - below_threshold_iqs: Below threshold queries (per-class supported)

    Args:
        detector_id: The detector ID.
        activity_type: Type of activity to record.
        class_index: For per-class tracking of escalations and below_threshold_iqs.
    """
    supported_activity_types = ["iqs", "escalations", "audits", "below_threshold_iqs"]

    if activity_type not in supported_activity_types:
        raise ValueError(
            f"The provided activity type ({activity_type}) is not currently supported. Supported types are: {supported_activity_types}"
        )

    logger.debug(f"Recording activity {activity_type} on detector {detector_id}")

    current_hour = datetime.now()

    # Record aggregate (always)
    f = _tracker().hourly_activity_file(activity_type, current_hour, detector_id)
    _tracker().increment_counter_file(f)

    # Record per-class for supported activity types
    if class_index is not None and activity_type in PER_CLASS_ACTIVITY_TYPES:
        per_class_prefix = f"{activity_type}_class_{class_index}"
        f = _tracker().hourly_activity_file(per_class_prefix, current_hour, detector_id)
        _tracker().increment_counter_file(f)
        logger.debug(f"Recording per-class {activity_type} for class {class_index} on detector {detector_id}")

    # per detector activity tracking
    f = _tracker().last_activity_file(activity_type, detector_id)
    f.touch()

    # edge endpoint wide activity tracking
    f = _tracker().last_activity_file(activity_type)
    f.touch()


@trace_span
def record_confidence_for_metrics(detector_id: str, confidence: float, class_index: int | None = None):
    """Records a confidence value from an image query for histogram tracking.

    Args:
        detector_id: The detector that processed the image query.
        confidence: The confidence value (0.0-1.0) from the inference result.
        class_index: The class index from the prediction.
                    If provided, records both aggregate and per-class histograms.
    """
    bucket = ConfidenceHistogramConfig.confidence_to_bucket(confidence)
    current_hour = datetime.now()

    # Record aggregate
    aggregate_prefix = f"{ConfidenceHistogramConfig.filename_prefix()}_{bucket}"
    f = _tracker().hourly_activity_file(aggregate_prefix, current_hour, detector_id)
    _tracker().increment_counter_file(f)

    # Record per-class (if class_index provided)
    if class_index is not None:
        per_class_prefix = f"{ConfidenceHistogramConfig.filename_prefix(class_index)}_{bucket}"
        f = _tracker().hourly_activity_file(per_class_prefix, current_hour, detector_id)
        _tracker().increment_counter_file(f)
        logger.debug(
            f"Recording confidence {confidence} (bucket {bucket}, class {class_index}) on detector {detector_id}"
        )
    else:
        logger.debug(
            f"Recording confidence {confidence} (bucket {bucket}) on detector {detector_id}, no class index provided"
        )


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
