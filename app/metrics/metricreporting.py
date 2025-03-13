import logging
import os
from datetime import datetime
from functools import lru_cache

from groundlight import Groundlight

from app.core import deviceid

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _groundlight_client() -> Groundlight:
    """Returns a Groundlight client instance with EE-wide credentials for reporting metrics."""
    # Don't specify an API token here - it will use the environment variable.
    return Groundlight()


def _metrics_payload() -> dict:
    """Returns a dictionary of metrics to be sent to the cloud API."""
    return {
        "device_id": deviceid.get_device_id(),
        "now": datetime.now().isoformat(),
        "cpucores": os.cpu_count(),
        # "gpucount": "",
        # "local_models": "TODO",
        # "last_image_processed": "TODO",
    }


def report_metrics():
    """Reports metrics to the cloud API."""
    payload = _metrics_payload()
    logger.info(f"Reporting metrics: {payload}")

    # Send the payload to the "/edge-metrics" endpoint in the cloud API
    # using the Groundlight SDK client.
    logger.info(f"Reporting metrics to the cloud API: {payload}")

    sdk = _groundlight_client()

    # TODO: replace this with a proper SDK call when available.
    headers = sdk.api_client._headers()  # API-token, user-agent, etc.
    response = sdk.api_client.call_api(
        resource_path="report-edge-metrics",  # The endpoint path
        method="POST",  # HTTP method
        header_params=headers,  # Custom headers
        body=payload,  # Your JSON payload
        async_req=False,  # Make synchronous request
        _return_http_data_only=True,  # Optional: return just the response data
    )
    logger.debug(f"Report edge metrics: {response}")
