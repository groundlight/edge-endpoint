"""Report metrics to the cloud API.
Is called by the main edge-endpoint web server.
Can also be run directly as a script.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Callable

from groundlight import Groundlight

from app.core import deviceid
from app.metrics import iq_activity, system_metrics

logger = logging.getLogger(__name__)


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
    """Class that collects metrics and reports them to the cloud API."""

    def __init__(self):
        self.metrics_to_send = {}

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

        return {
            "device_info": device_info.as_dict(),
            "activity_metrics": activity_metrics.as_dict(),
            "k3s_stats": k3s_stats.as_dict(),
        }

    def collect_metrics_for_cloud(self):
        """Collect metrics for the cloud API."""
        payload = self.metrics_payload()
        self.metrics_to_send[datetime.now().isoformat()] = payload

    def report_metrics_to_cloud(self):
        """Reports metrics to the cloud API."""
        sdk = _groundlight_client()
        # TODO: replace this with a proper SDK call when available.
        headers = sdk.api_client._headers()

        for timestamp, payload in sorted(self.metrics_to_send.items(), key=lambda x: x[0]):
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
                del self.metrics_to_send[timestamp]
            else:
                logger.error(f"Error reporting metrics to the cloud API: {response}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    reporter = MetricsReporter()
    reporter.collect_metrics_for_cloud()
    reporter.report_metrics_to_cloud()
