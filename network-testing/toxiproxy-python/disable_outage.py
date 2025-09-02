#!/usr/bin/env python3
import sys

from common import get_namespace, http_request, port_forward_service, service_exists

HTTP_NOT_FOUND = 404


def main() -> int:
    ns = get_namespace()

    if not service_exists("toxiproxy", ns):
        print(f"Toxiproxy is not installed in namespace {ns}.")
        return 0

    with port_forward_service(ns) as base_url:
        # Re-enable proxy (if it was disabled)
        r = http_request("POST", f"{base_url}/proxies/api_groundlight_ai", {"enabled": True})
        if r.status_code not in {200, 201}:
            print(f"Warning: could not enable proxy (HTTP {r.status_code}).")

        # Remove timeout toxics if present
        for name in ("outage_timeout_up", "outage_timeout_down"):
            r = http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/{name}")
            if r.status_code in {200, 204}:
                print(f"Removed {name}.")
            elif r.status_code == HTTP_NOT_FOUND:
                print(f"{name} not present.")
            else:
                print(f"Unexpected response removing {name}: HTTP {r.status_code}")

    print("Outage disabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
