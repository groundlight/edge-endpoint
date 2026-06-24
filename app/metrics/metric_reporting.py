"""Report metrics to the cloud API.
Is called by the main edge-endpoint web server.
Can also be run directly as a script.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from groundlight import Groundlight

from app.core import deviceid
from app.escalation_queue import failed_escalations
from app.metrics import iq_activity, system_metrics

logger = logging.getLogger(__name__)

# Directory where sealed hourly snapshots awaiting delivery to the cloud are persisted, alongside the
# device-local activity counters. Persisting them (rather than only holding them in memory) means a
# retry -- even across a process restart -- re-sends the *identical* sealed snapshot instead of
# re-reading the live counters, which would produce a different total for the same (immutable) hour
# and be permanently rejected by the cloud's unique (hour, device, detector) constraint.
PENDING_REPORTS_DIR = Path("/opt/groundlight/device/edge-metrics/pending-cloud-reports")

# Drop (stop retrying) a pending report once its hour is older than this. Late delivery is otherwise
# fine -- the hour is immutable -- but this bounds disk growth if a report can never be delivered.
PENDING_REPORT_MAX_AGE = timedelta(days=7)


@lru_cache(maxsize=1)
def _groundlight_client() -> Groundlight:
    """Returns a Groundlight client instance with EE-wide credentials for reporting metrics."""
    # Don't specify an API token here - it will use the environment variable.
    return Groundlight()


class SafeMetricsDict:
    """Utility class that makes it easy to call possibly-unreliable functions for metrics,
    and not worry about the entire payload failing to report because of one
    function throwing an exception or returning bad data.  (Seen this too many times.)
    """

    def __init__(self):
        self.data = {}

    def add(self, key: str, lambda_fn: Callable[[], Any]):
        try:
            value = lambda_fn()
            json.dumps(value)  # don't add non-JSON-serializable values
            self.data[key] = value
        except Exception as e:
            logger.error(f"Error adding metric {key}: {e}", exc_info=True)
            self.data[key] = {"error": str(e)}

    def as_dict(self) -> dict:
        return self.data


class MetricsReporter:
    """Collects metrics and reports them to the cloud API.

    Hourly reporting is idempotent and durable. Each previous-hour snapshot is keyed by its
    ``activity_hour`` (first-writer-wins) and persisted to disk, so a re-collection (e.g. a scheduler
    misfire) or a retry after a process restart re-sends the exact same sealed snapshot rather than
    re-reading the live counters. The cloud stores each (hour, device, detector) row immutably, so a
    second, differently-valued snapshot for the same hour would be permanently rejected -- which is
    the failure mode this is designed to avoid.
    """

    def __init__(self, pending_reports_dir: str | Path | None = None):
        self.pending_reports_dir = Path(pending_reports_dir) if pending_reports_dir else PENDING_REPORTS_DIR
        # Maps activity_hour -> sealed payload; mirrors the persisted snapshot files on disk.
        self.metrics_to_send: dict[str, dict] = {}

    def metrics_payload(self) -> dict:
        """Returns a dictionary of metrics to be sent to the cloud API."""
        device_info = SafeMetricsDict()
        device_info.add("device_id", lambda: deviceid.get_deviceid_str())
        device_info.add("device_metadata", lambda: deviceid.get_deviceid_metadata_dict())
        device_info.add("now", lambda: datetime.now().isoformat())
        device_info.add("cpucores", lambda: os.cpu_count())
        device_info.add("inference_flavor", lambda: system_metrics.get_inference_flavor())
        device_info.add("cpu_utilization", lambda: system_metrics.get_cpu_utilization())
        device_info.add("memory_utilization", lambda: system_metrics.get_memory_utilization())
        device_info.add("memory_available_bytes", lambda: system_metrics.get_memory_available_bytes())

        activity_metrics = SafeMetricsDict()
        retriever = iq_activity.ActivityRetriever()
        activity_metrics.add("activity_hour", lambda: retriever.get_last_hour())
        activity_metrics.add("last_activity_time", lambda: retriever.last_activity_time())
        activity_metrics.add("num_detectors_lifetime", lambda: retriever.num_detectors_lifetime())
        activity_metrics.add("num_detectors_active_1h", lambda: retriever.num_detectors_active(timedelta(hours=1)))
        activity_metrics.add("num_detectors_active_24h", lambda: retriever.num_detectors_active(timedelta(days=1)))
        activity_metrics.add("detector_activity_previous_hour", lambda: retriever.get_active_detector_activity())

        k3s_stats = SafeMetricsDict()
        k3s_stats.add("deployments", lambda: system_metrics.get_deployments())
        k3s_stats.add("pod_statuses", lambda: system_metrics.get_pods())
        k3s_stats.add("container_images", lambda: system_metrics.get_container_images())

        detector_details = SafeMetricsDict()
        detector_details.add("detector_details", lambda: system_metrics.get_detector_details())

        failed_escalation_metrics = SafeMetricsDict()
        failed_escalation_metrics.add("failed_escalations", lambda: failed_escalations.metrics_summary())

        return {
            "device_info": device_info.as_dict(),
            "activity_metrics": activity_metrics.as_dict(),
            "failed_escalations": failed_escalation_metrics.as_dict().get("failed_escalations"),
            "detector_details": detector_details.as_dict().get("detector_details"),
            "k3s_stats": k3s_stats.as_dict(),
        }

    def _report_path(self, key: str) -> Path:
        """On-disk path for a queued snapshot. ``key`` is the activity_hour, e.g. '2026-06-24_15'."""
        return self.pending_reports_dir / f"{key}.json"

    def _persist_report(self, key: str, payload: dict) -> None:
        """Atomically write a sealed snapshot to disk so it survives a process restart."""
        try:
            self.pending_reports_dir.mkdir(parents=True, exist_ok=True)
            path = self._report_path(key)
            tmp_path = path.with_name(f"{path.name}.tmp")
            tmp_path.write_text(json.dumps(payload))
            tmp_path.replace(path)  # atomic rename on POSIX; never leaves a half-written .json
        except OSError as e:
            logger.error(f"Could not persist pending metrics report for {key}: {e}", exc_info=True)

    def _discard_report(self, key: str) -> None:
        """Forget a snapshot (in memory and on disk) once it's been delivered or pruned."""
        self.metrics_to_send.pop(key, None)
        try:
            self._report_path(key).unlink(missing_ok=True)
        except OSError as e:
            logger.error(f"Could not delete pending metrics report for {key}: {e}", exc_info=True)

    def load_pending_reports(self) -> None:
        """Reload snapshots that were queued before a restart. Call once at startup, before reporting."""
        if not self.pending_reports_dir.exists():
            return
        for path in sorted(self.pending_reports_dir.glob("*.json")):
            try:
                self.metrics_to_send[path.stem] = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Could not load pending metrics report {path}; deleting it: {e}", exc_info=True)
                path.unlink(missing_ok=True)
        if self.metrics_to_send:
            logger.info(f"Reloaded {len(self.metrics_to_send)} pending metrics report(s) from disk.")

    def _prune_stale_reports(self) -> None:
        """Drop pending reports whose hour is older than ``PENDING_REPORT_MAX_AGE`` to bound disk growth."""
        cutoff = datetime.now(timezone.utc) - PENDING_REPORT_MAX_AGE
        for key in list(self.metrics_to_send):
            try:
                hour = datetime.strptime(key, "%Y-%m-%d_%H").replace(tzinfo=timezone.utc)
            except ValueError:
                continue  # not an activity_hour key (in-memory fallback); leave it alone
            if hour < cutoff:
                logger.warning(
                    f"Dropping undeliverable metrics report for activity_hour={key} "
                    f"(older than {PENDING_REPORT_MAX_AGE})."
                )
                self._discard_report(key)

    def collect_metrics_for_cloud(self):
        """Seal the previous hour's metrics once and queue them for delivery.

        Keyed by ``activity_hour`` with first-writer-wins: if the hour has already been sealed
        (earlier in this run, or persisted before a restart), we keep that snapshot instead of
        re-reading the counters, which would yield a different total for the same immutable hour.
        """
        payload = self.metrics_payload()
        activity_hour = payload.get("activity_metrics", {}).get("activity_hour")

        if not isinstance(activity_hour, str):
            # Couldn't determine the hour (e.g. the clock read failed and SafeMetricsDict stored an
            # error dict). Queue in memory under a unique key so we still attempt a send, but don't
            # persist or dedup it.
            logger.warning(f"No usable activity_hour in metrics payload; queueing without dedup. got={activity_hour!r}")
            self.metrics_to_send[datetime.now().isoformat()] = payload
            return

        if activity_hour in self.metrics_to_send or self._report_path(activity_hour).exists():
            logger.info(f"Metrics for activity_hour={activity_hour} already sealed; keeping the original snapshot.")
            return

        self._persist_report(activity_hour, payload)
        self.metrics_to_send[activity_hour] = payload

    def report_metrics_to_cloud(self):
        """Reports any queued (sealed) metrics snapshots to the cloud API."""
        self._prune_stale_reports()
        sdk = _groundlight_client()
        # TODO: replace this with a proper SDK call when available.
        headers = sdk.api_client._headers()

        for key, payload in sorted(self.metrics_to_send.items(), key=lambda x: x[0]):
            logger.info(f"Reporting metrics to the cloud API: {payload}")
            response = sdk.api_client.call_api(
                # We have to do this in order because it analyzes *args.  Grrr.
                "/v1/edge/report-metrics",  # The endpoint path
                "POST",  # HTTP method
                None,  # path_params
                None,  # query_params
                headers,  # header_params
                payload,  # body
                async_req=False,  # async_req
            )
            logger.info(f"Report edge metrics: {response}")
            # Returns a tuple of (return_data, status, headers)
            if response[1] == 200:
                logger.info(f"Metrics reported successfully: {response}")
                self._discard_report(key)
            else:
                logger.error(f"Error reporting metrics to the cloud API: {response}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    reporter = MetricsReporter()
    reporter.load_pending_reports()
    reporter.collect_metrics_for_cloud()
    reporter.report_metrics_to_cloud()
