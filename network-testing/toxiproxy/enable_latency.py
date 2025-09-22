#!/usr/bin/env python3
import argparse
import sys

from common import get_namespace, port_forward_service, post_proxy_method, require_toxiproxy_installed
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
        status_code = post_proxy_method(
            base_url,
            "toxics",
            {
                "name": name,
                "type": "latency",
                "stream": stream,
                "attributes": {"latency": lat_ms, "jitter": jitter_ms},
            },
        )
        if status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
            return
        if status_code == status.HTTP_409_CONFLICT:
            # Toxic already exists; try to update its attributes
            status_code2 = post_proxy_method(
                base_url,
                f"toxics/{name}",
                {"attributes": {"latency": lat_ms, "jitter": jitter_ms}},
            )
            if status_code2 in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                print(f"Toxic {name} already existed; attributes updated.")
            else:
                print(f"Toxic {name} already exists; failed to update attributes (HTTP {status_code2}).")
            return
        print(f"Warning: creating toxic {name} returned HTTP {status_code}")

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
