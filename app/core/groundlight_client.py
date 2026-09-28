from functools import lru_cache
from urllib.parse import urlsplit

from groundlight import ExperimentalApi
from groundlight.internalapi import sanitize_endpoint_url


@lru_cache(maxsize=1)
def groundlight_client() -> ExperimentalApi:
    """Return a cached, endpoint-wide Groundlight client for talking to the cloud.

    Authenticates with the endpoint's environment-provided API token and cloud endpoint
    (GROUNDLIGHT_API_TOKEN / GROUNDLIGHT_ENDPOINT), so it always points at the cloud this
    device is registered to. Returns ExperimentalApi so call sites can reach EdgeApi
    helpers (model URLs, metrics) through the same device client.
    """
    # Don't specify an API token here - it will use the environment variable.
    return ExperimentalApi()  # NOTE this will wait the default 10 seconds when there's no connection.


def upstream_endpoint() -> str:
    """Return the origin (scheme://host[:port]) of the cloud that groundlight_client() talks to.

    Resolved from GROUNDLIGHT_ENDPOINT the same way the SDK does, without contacting the cloud.
    """
    parts = urlsplit(sanitize_endpoint_url())
    return f"{parts.scheme}://{parts.netloc}"
