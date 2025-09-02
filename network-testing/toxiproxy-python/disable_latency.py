#!/usr/bin/env python3
import sys

from common import get_namespace, http_request, port_forward_service

HTTP_NOT_FOUND = 404


def main() -> int:
    ns = get_namespace()

    print("Removing latency toxics if present")

    # Ensure toxiproxy service exists
    # We intentionally skip a hard check here; DELETE will simply 404 if missing

    with port_forward_service(ns) as base_url:
        for name in ("fixed_latency_up", "fixed_latency_down"):
            r = http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/{name}")
            if r.status_code in {200, 204}:
                print(f"Toxic {name} removed.")
            elif r.status_code == HTTP_NOT_FOUND:
                print(f"Toxic {name} was not present.")
            else:
                print(f"Toxic {name}: unexpected response code {r.status_code}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
