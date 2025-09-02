#!/usr/bin/env python3
import sys

from common import get_namespace, http_request, port_forward_service, require_toxiproxy_installed
from fastapi import status


def main() -> int:
    ns = get_namespace()

    require_toxiproxy_installed(ns, exit_code=0)

    with port_forward_service(ns) as base_url:
        # Re-enable proxy (if it was disabled by outage/refuse mode)
        r = http_request("POST", f"{base_url}/proxies/api_groundlight_ai", {"enabled": True})
        if r.status_code not in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
            print(f"Warning: could not enable proxy (HTTP {r.status_code}).")

    print("Outage disabled: proxy enabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
