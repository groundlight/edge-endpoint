from functools import lru_cache

from groundlight import Groundlight


@lru_cache(maxsize=1)
def groundlight_client() -> Groundlight:
    """Return a cached, endpoint-wide Groundlight client for talking to the cloud.

    Authenticates with the endpoint's environment-provided API token and cloud endpoint
    (GROUNDLIGHT_API_TOKEN / GROUNDLIGHT_ENDPOINT), so it always points at the cloud this
    device is registered to.
    """
    # Don't specify an API token here - it will use the environment variable.
    return Groundlight()  # NOTE this will wait the default 10 seconds when there's no connection.
