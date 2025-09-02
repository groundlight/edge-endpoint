#!/usr/bin/env python3
import argparse
import sys

from common import (
    get_namespace,
    http_request,
    port_forward_service,
    service_exists,
    sleep_ms,
)


def main() -> int:
    ns = get_namespace()

    if not service_exists("toxiproxy", ns):
        print(f"Toxiproxy is not installed in namespace {ns}. Run enable_toxiproxy.py first.", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(description="Flap simulated outage via Toxiproxy")
    parser.add_argument("--mode", choices=["refuse", "blackhole"], default="blackhole")
    parser.add_argument("--up-ms", type=int, default=15000)
    parser.add_argument("--down-ms", type=int, default=15000)
    parser.add_argument("--blackhole-ms", type=int, default=30000)
    parser.add_argument("--blackhole-stream", choices=["up", "down", "both"], default="both")
    parser.add_argument("--iterations", type=int, default=0, help="0=infinite until SIGINT")
    args = parser.parse_args()

    mode = args.mode
    up_ms = max(args.up_ms, 0)
    down_ms = max(args.down_ms, 0)
    bh_ms = max(args.blackhole_ms, 0)
    bh_stream = args.blackhole_stream
    iterations = max(args.iterations, 0)

    def cleanup() -> None:
        with port_forward_service(ns) as base_url:
            if mode == "refuse":
                http_request("POST", f"{base_url}/proxies/api_groundlight_ai", {"enabled": True})
            else:
                http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_up")
                http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_down")
        print("\nFlapping stopped. Cleaned up.")

    print(
        "Starting outage flapping: "
        f"mode={mode} up={up_ms}ms down={down_ms}ms "
        f"(blackhole-ms={bh_ms}, stream={bh_stream})"
    )

    count = 0
    try:
        while True:
            # UP period (normal)
            with port_forward_service(ns) as base_url:
                if mode == "refuse":
                    http_request("POST", f"{base_url}/proxies/api_groundlight_ai", {"enabled": True})
                else:
                    # Ensure timeout toxics removed during UP
                    http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_up")
                    http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_down")
            print(".", end="", flush=True)
            sleep_ms(up_ms)

            # DOWN period (outage)
            with port_forward_service(ns) as base_url:
                if mode == "refuse":
                    http_request("POST", f"{base_url}/proxies/api_groundlight_ai", {"enabled": False})
                else:
                    if bh_stream in {"up", "both"}:
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
                        if r.status_code not in {200, 201}:
                            http_request(
                                "POST",
                                f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_up",
                                {"attributes": {"timeout": bh_ms}},
                            )
                    else:
                        http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_up")
                    if bh_stream in {"down", "both"}:
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
                        if r.status_code not in {200, 201}:
                            http_request(
                                "POST",
                                f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_down",
                                {"attributes": {"timeout": bh_ms}},
                            )
                    else:
                        http_request("DELETE", f"{base_url}/proxies/api_groundlight_ai/toxics/outage_timeout_down")
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
