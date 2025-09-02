#!/usr/bin/env python3
import argparse
import sys

from common import get_namespace, http_request, port_forward_service


def main() -> int:
    ns = get_namespace()

    parser = argparse.ArgumentParser(description="Add latency toxic(s) to api_groundlight_ai proxy")
    parser.add_argument("latency_ms", type=int, help="Fixed latency in milliseconds")
    parser.add_argument("--jitter", type=int, default=0)
    parser.add_argument("--direction", choices=["down", "up", "both"], default="down")
    args = parser.parse_args()

    lat_ms = max(args.latency_ms, 0)
    jitter_ms = max(args.jitter, 0)

    print(f"Adding latency toxic(s): direction={args.direction} latency={lat_ms}ms jitter={jitter_ms}ms")

    def add_one(base_url: str, name: str, stream: str) -> None:
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
        if r.status_code not in {200, 201}:
            print(f"Warning: creating toxic {name} returned HTTP {r.status_code}")

    with port_forward_service(ns) as base_url:
        if args.direction == "down":
            add_one(base_url, "fixed_latency_down", "downstream")
        elif args.direction == "up":
            add_one(base_url, "fixed_latency_up", "upstream")
        else:
            add_one(base_url, "fixed_latency_up", "upstream")
            add_one(base_url, "fixed_latency_down", "downstream")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
