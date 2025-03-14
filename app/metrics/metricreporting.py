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
    deviceid_dict = deviceid.get_deviceid_dict()
    deviceid_str = deviceid_dict["uuid"]
    return {
        "device_id": deviceid_str,
        "device_metadata": deviceid_dict,
        "now": datetime.now().isoformat(),
        "cpucores": os.cpu_count(),
        # "gpucount": "",
        # "local_models": "TODO",
        # "last_image_processed": "TODO",
    }


def report_metrics():
    """Reports metrics to the cloud API."""
    payload = _metrics_payload()

    logger.info(f"Reporting metrics to the cloud API: {payload}")

    sdk = _groundlight_client()
    # TODO: replace this with a proper SDK call when available.
    headers = sdk.api_client._headers()
    response = sdk.api_client.call_api(
        # We have to do this in order because it analyzes *args.  Grrr.
        "/v1/edge/report-metrics",  # The endpoint path
        "POST",                 # HTTP method
        None,            # path_params
        None,           # query_params
        headers,         # header_params
        payload,                  # body
        async_req=False,               # async_req
        _return_http_data_only=True    # _return_http_data_only
    )
    logger.debug(f"Report edge metrics: {response}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    report_metrics()
