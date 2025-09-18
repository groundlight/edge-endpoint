#!/usr/bin/env python3
import sys

from common import delete_proxy_method, get_namespace, port_forward_service, require_toxiproxy_installed
from fastapi import status

HTTP_NOT_FOUND = 404


def main() -> int:
    ns = get_namespace()

    require_toxiproxy_installed(ns, exit_code=0)

    print("Removing latency toxics if present")

    # Ensure toxiproxy service exists
    # We intentionally skip a hard check here; DELETE will simply 404 if missing

    with port_forward_service(ns) as base_url:
        for name in ("fixed_latency_up", "fixed_latency_down"):
            status_code = delete_proxy_method(base_url, f"toxics/{name}")
            if status_code in {status.HTTP_200_OK, status.HTTP_204_NO_CONTENT}:
                print(f"Toxic {name} removed.")
            elif status_code == status.HTTP_404_NOT_FOUND:
                print(f"Toxic {name} was not present.")
            else:
                print(f"Toxic {name}: unexpected response code {status_code}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
