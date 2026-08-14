from functools import lru_cache

from groundlight import ExperimentalApi


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
