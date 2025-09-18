#!/usr/bin/env python3
import argparse
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

    require_toxiproxy_installed(ns, exit_code=1)

    parser = argparse.ArgumentParser(description="Enable simulated timeout via Toxiproxy (timeout toxics)")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--timeout-stream", choices=["up", "down", "both"], default="both")
    args = parser.parse_args()

    to_ms = max(args.timeout_ms, 0)
    stream = args.timeout_stream
    print(f"Enabling timeout via timeout toxics: {to_ms}ms on {stream} stream(s)")

    with port_forward_service(ns) as base_url:
        if stream in {"up", "both"}:
            status_code = post_proxy_method(
                base_url,
                "toxics",
                {
                    "name": "timeout_up",
                    "type": "timeout",
                    "stream": "upstream",
                    "attributes": {"timeout": to_ms},
                },
            )
            if status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                pass
            elif status_code == status.HTTP_409_CONFLICT:
                status_code_upd = post_proxy_method(
                    base_url,
                    "toxics/timeout_up",
                    {"attributes": {"timeout": to_ms}},
                )
                if status_code_upd in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                    print("Toxic timeout_up already existed; attributes updated.")
                else:
                    print(
                        f"Toxic timeout_up already exists; failed to update attributes (HTTP {status_code_upd}).",
                        file=sys.stderr,
                    )
                    return 1
            else:
                print("Failed to ensure upstream timeout toxic", file=sys.stderr)
                return 1
        else:
            delete_proxy_method(base_url, "toxics/timeout_up")

        if stream in {"down", "both"}:
            status_code = post_proxy_method(
                base_url,
                "toxics",
                {
                    "name": "timeout_down",
                    "type": "timeout",
                    "stream": "downstream",
                    "attributes": {"timeout": to_ms},
                },
            )
            if status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                pass
            elif status_code == status.HTTP_409_CONFLICT:
                status_code_upd = post_proxy_method(
                    base_url,
                    "toxics/timeout_down",
                    {"attributes": {"timeout": to_ms}},
                )
                if status_code_upd in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
                    print("Toxic timeout_down already existed; attributes updated.")
                else:
                    print(
                        f"Toxic timeout_down already exists; failed to update attributes (HTTP {status_code_upd}).",
                        file=sys.stderr,
                    )
                    return 1
            else:
                print("Failed to ensure downstream timeout toxic", file=sys.stderr)
                return 1
        else:
            delete_proxy_method(base_url, "toxics/timeout_down")

    print(f"Timeout enabled: connections will hang up to {to_ms}ms on {stream}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
