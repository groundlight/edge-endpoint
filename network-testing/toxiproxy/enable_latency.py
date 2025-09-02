#!/usr/bin/env python3
import argparse
import sys

from common import get_namespace, http_request, port_forward_service, require_toxiproxy_installed
from fastapi import status


def main() -> int:
    ns = get_namespace()

    require_toxiproxy_installed(ns, exit_code=1)

    parser = argparse.ArgumentParser(description="Add latency toxic(s) to api_groundlight_ai proxy")
    parser.add_argument("latency_ms", type=int, help="Fixed latency in milliseconds")
    parser.add_argument("--jitter", type=int, default=0)
    parser.add_argument("--direction", choices=["down", "up", "both"], default="up")
    args = parser.parse_args()

    lat_ms = max(args.latency_ms, 0)
    jitter_ms = max(args.jitter, 0)

    print(f"Adding latency toxic(s): direction={args.direction} latency={lat_ms}ms jitter={jitter_ms}ms")

    def add_latency_toxic(base_url: str, name: str, stream: str) -> None:
        r = http_request(
            "POST",
            f"{base_url}/proxies/api_groundlight_ai/toxics",
            {
                "name": name,
                "type": "latency",
                "stream": stream,
                "attributes": {"latency": lat_ms, "jitter": jitter_ms},
            },
        )
        if r.status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
            return
        if r.status_code == status.HTTP_409_CONFLICT:
            # Toxic already exists; try to update its attributes
            r2 = http_request(
                "POST",
                f"{base_url}/proxies/api_groundlight_ai/toxics/{name}",
                {"attributes": {"latency": lat_ms, "jitter": jitter_ms}},
            )
            if r2.status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                print(f"Toxic {name} already existed; attributes updated.")
            else:
                print(f"Toxic {name} already exists; failed to update attributes (HTTP {r2.status_code}).")
            return
        print(f"Warning: creating toxic {name} returned HTTP {r.status_code}")

    with port_forward_service(ns) as base_url:
        if args.direction == "down":
            add_latency_toxic(base_url, "fixed_latency_down", "downstream")
        elif args.direction == "up":
            add_latency_toxic(base_url, "fixed_latency_up", "upstream")
        else:
            add_latency_toxic(base_url, "fixed_latency_up", "upstream")
            add_latency_toxic(base_url, "fixed_latency_down", "downstream")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
