import os
from typing import Optional, Type

import requests
from requests import Response

REMOTE_URL = os.getenv("REMOTE_URL", default="https://api.integ.groundlight.ai")


def remote_request(path: str, method: str = "get", body: Optional[dict] = None, url: str = REMOTE_URL) -> Response:
    http_method: Type[requests.get] | Type[requests.post] | Type[requests.patch] = getattr(requests, method)
    full_url = f"{url}{path}"
    response: Response = http_method(url=full_url, json=body, timeout=30)
    response.raise_for_status()
    return response
