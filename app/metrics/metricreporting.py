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
from app.metrics import iqactivity, system_metrics

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


def metrics_payload() -> dict:
    """Returns a dictionary of metrics to be sent to the cloud API."""
    out = SafeMetricsDict()
    out.add("device_id", lambda: deviceid.get_deviceid_str())
    out.add("device_metadata", lambda: deviceid.get_deviceid_metadata_dict())
    out.add("now", lambda: datetime.now().isoformat())
    out.add("cpucores", lambda: os.cpu_count())
    out.add("last_image_processed", lambda: iqactivity.last_activity_time())
    out.add("num_detectors_lifetime", lambda: iqactivity.num_detectors_lifetime())
    out.add("num_detectors_active_1h", lambda: iqactivity.num_detectors_active(timedelta(hours=1)))
    out.add("num_detectors_active_24h", lambda: iqactivity.num_detectors_active(timedelta(days=1)))
    # TODO: Add pod.status.containerStatuses[].imageId
    # TODO: add metrics like GPU count, how many local models, etc
    out.add("cpu_usage", lambda: system_metrics.get_cpu_usage())
    out.add("percentage_memory_used", lambda: system_metrics.get_percentage_memory_used())
    out.add("memory_available", lambda: system_metrics.get_memory_available())
    out.add("deployments_list", lambda: system_metrics.get_deployments())
    out.add("pods_list", lambda: system_metrics.get_pods())
    return out.as_dict()


def report_metrics_to_cloud():
    """Reports metrics to the cloud API."""
    payload = metrics_payload()

    logger.info(f"Reporting metrics to the cloud API: {payload}")

    sdk = _groundlight_client()
    # TODO: replace this with a proper SDK call when available.
    headers = sdk.api_client._headers()
    response = sdk.api_client.call_api(
        # We have to do this in order because it analyzes *args.  Grrr.
        "/v1/edge/report-metrics",  # The endpoint path
        "POST",  # HTTP method
        None,  # path_params
        None,  # query_params
        headers,  # header_params
        payload,  # body
        async_req=False,  # async_req
        _return_http_data_only=True,  # _return_http_data_only
    )
    logger.debug(f"Report edge metrics: {response}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    report_metrics_to_cloud()
