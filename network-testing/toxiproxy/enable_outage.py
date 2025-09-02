#!/usr/bin/env python3
import argparse
import sys

from common import get_namespace, http_request, port_forward_service, require_toxiproxy_installed
from fastapi import status


def main() -> int:
    ns = get_namespace()

    require_toxiproxy_installed(ns, exit_code=1)

    parser = argparse.ArgumentParser(description="Enable simulated outage via Toxiproxy")
    parser.add_argument("--mode", choices=["refuse", "blackhole"], default="blackhole")
    parser.add_argument("--blackhole-ms", type=int, default=30000)
    parser.add_argument("--blackhole-stream", choices=["up", "down", "both"], default="both")
    args = parser.parse_args()

    if args.mode == "refuse":
        with port_forward_service(ns) as base_url:
            r = http_request("POST", f"{base_url}/proxies/api_groundlight_ai", {"enabled": False})
            if r.status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                print("Outage enabled: proxy disabled (connections will be refused).")
                return 0
            else:
                print(f"Failed to disable proxy. HTTP {r.status_code}", file=sys.stderr)
                return 1

    # blackhole mode
    bh_ms = max(args.blackhole_ms, 0)
    stream = args.blackhole_stream
    print(f"Enabling blackhole outage via timeout toxics: {bh_ms}ms on {stream} stream(s)")

    with port_forward_service(ns) as base_url:
        if stream in {"up", "both"}:
            r = http_request(
                "POST",
                f"{base_url}/proxies/api_groundlight_ai/toxics",
                {
                    "name": "outage_timeout_up",
                    "type": "timeout",
                    "stream": "upstream",
                    "attributes": {"timeout": bh_ms},
                },
            )
            if r.status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                pass
            elif r.status_code == status.HTTP_409_CONFLICT:
                r_upd = http_request(
                    "POST",
                    f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_up",
                    {"attributes": {"timeout": bh_ms}},
                )
                if r_upd.status_code in {200, 201}:
                    print("Toxic outage_timeout_up already existed; attributes updated.")
                else:
                    print(
                        f"Toxic outage_timeout_up already exists; failed to update attributes (HTTP {r_upd.status_code}).",
                        file=sys.stderr,
                    )
                    return 1
            else:
                print("Failed to ensure upstream timeout toxic", file=sys.stderr)
                return 1
        else:
            http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_up")

        if stream in {"down", "both"}:
            r = http_request(
                "POST",
                f"{base_url}/proxies/api_groundlight_ai/toxics",
                {
                    "name": "outage_timeout_down",
                    "type": "timeout",
                    "stream": "downstream",
                    "attributes": {"timeout": bh_ms},
                },
            )
            if r.status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                pass
            elif r.status_code == status.HTTP_409_CONFLICT:
                r_upd = http_request(
                    "POST",
                    f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_down",
                    {"attributes": {"timeout": bh_ms}},
                )
                if r_upd.status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                    print("Toxic outage_timeout_down already existed; attributes updated.")
                else:
                    print(
                        f"Toxic outage_timeout_down already exists; failed to update attributes (HTTP {r_upd.status_code}).",
                        file=sys.stderr,
                    )
                    return 1
            else:
                print("Failed to ensure downstream timeout toxic", file=sys.stderr)
                return 1
        else:
            http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_down")

    print(f"Outage enabled: connections will hang up to {bh_ms}ms on {stream}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
