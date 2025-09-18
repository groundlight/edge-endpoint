#!/usr/bin/env python3
import sys

from common import (
    delete_proxy_method,
    get_namespace,
    port_forward_service,
    post_proxy_method,
    require_toxiproxy_installed,
)
from fastapi import status


def main() -> int:
    ns = get_namespace()

    require_toxiproxy_installed(ns, exit_code=0)

    with port_forward_service(ns) as base_url:
        # Re-enable proxy (if it was disabled)
        status_code = post_proxy_method(base_url, "", {"enabled": True})
        if status_code not in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
            print(f"Warning: could not enable proxy (HTTP {status_code}).")

        # Remove timeout toxics if present
        for name in ("timeout_up", "timeout_down"):
            status_code = delete_proxy_method(base_url, f"toxics/{name}")
            if status_code in {status.HTTP_200_OK, status.HTTP_204_NO_CONTENT}:
                print(f"Removed {name}.")
            elif status_code == status.HTTP_404_NOT_FOUND:
                print(f"{name} not present.")
            else:
                print(f"Unexpected response removing {name}: HTTP {status_code}")

    print("Timeout disabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
