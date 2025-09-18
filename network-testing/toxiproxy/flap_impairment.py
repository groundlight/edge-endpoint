#!/usr/bin/env python3
import argparse
import sys

from common import (
    delete_proxy_method,
    get_namespace,
    port_forward_service,
    post_proxy_method,
    require_toxiproxy_installed,
    sleep_ms,
)


def main() -> int:
    ns = get_namespace()

    require_toxiproxy_installed(ns, exit_code=1)

    parser = argparse.ArgumentParser(description="Flap simulated connectivity impairments (refuse or timeout)")
    parser.add_argument("--mode", choices=["refuse", "timeout"], default="timeout")
    parser.add_argument("--up-ms", type=int, default=15000)
    parser.add_argument("--down-ms", type=int, default=15000)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--timeout-stream", choices=["up", "down", "both"], default="both")
    parser.add_argument("--iterations", type=int, default=0, help="0=infinite until SIGINT")
    args = parser.parse_args()

    mode = args.mode
    up_ms = max(args.up_ms, 0)
    down_ms = max(args.down_ms, 0)
    to_ms = max(args.timeout_ms, 0)
    to_stream = args.timeout_stream
    iterations = max(args.iterations, 0)

    def cleanup() -> None:
        with port_forward_service(ns) as base_url:
            if mode == "refuse":
                post_proxy_method(base_url, "", {"enabled": True})
            else:
                delete_proxy_method(base_url, "toxics/timeout_up")
                delete_proxy_method(base_url, "toxics/timeout_down")
        print("\nFlapping stopped. Cleaned up.")

    msg = f"Starting impairment flapping: mode={mode} up={up_ms}ms down={down_ms}ms"
    if mode == "timeout":
        msg += f" (timeout-ms={to_ms}, stream={to_stream})"
    print(msg)

    count = 0
    try:
        while True:
            # UP period (normal)
            with port_forward_service(ns) as base_url:
                if mode == "refuse":
                    post_proxy_method(base_url, "", {"enabled": True})
                else:
                    # Ensure timeout toxics removed during UP
                    delete_proxy_method(base_url, "toxics/timeout_up")
                    delete_proxy_method(base_url, "toxics/timeout_down")
            print(".", end="", flush=True)
            sleep_ms(up_ms)

            # DOWN period (impairment)
            with port_forward_service(ns) as base_url:
                if mode == "refuse":
                    post_proxy_method(base_url, "", {"enabled": False})
                else:
                    if to_stream in {"up", "both"}:
                        post_proxy_method(
                            base_url,
                            "toxics",
                            {
                                "name": "timeout_up",
                                "type": "timeout",
                                "stream": "upstream",
                                "attributes": {"timeout": to_ms},
                            },
                        )
                    else:
                        delete_proxy_method(base_url, "toxics/timeout_up")
                    if to_stream in {"down", "both"}:
                        post_proxy_method(
                            base_url,
                            "toxics",
                            {
                                "name": "timeout_down",
                                "type": "timeout",
                                "stream": "downstream",
                                "attributes": {"timeout": to_ms},
                            },
                        )
                    else:
                        delete_proxy_method(base_url, "toxics/timeout_down")
            print("x", end="", flush=True)
            sleep_ms(down_ms)

            if iterations > 0:
                count += 1
                if count >= iterations:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
