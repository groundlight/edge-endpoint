#!/usr/bin/env python3
import json
import sys

from common import get_namespace, http_request, port_forward_service, service_exists

HTTP_NOT_FOUND = 404


def main() -> int:
    ns = get_namespace()

    if not service_exists("toxiproxy", ns):
        print(f"Toxiproxy is not installed in namespace {ns}.")
        return 0

    with port_forward_service(ns) as base_url:
        r = http_request("GET", f"{base_url}/proxies/api_groundlight_ai")
        if r.status_code == HTTP_NOT_FOUND:
            print("Proxy 'api_groundlight_ai' not found. Run enable_toxiproxy.py first.")
            return 0

        r = http_request("GET", f"{base_url}/proxies/api_groundlight_ai/toxics")
        body = r.text
        if not body:
            print("No response from Toxiproxy admin API.")
            return 1

    print("Current toxics on api_groundlight_ai:")
    try:
        data = json.loads(body)
        if not data:
            print("- none")
        else:
            for toxic in data:
                name = toxic.get("name", "?")
                ttype = toxic.get("type", "?")
                stream = toxic.get("stream", "?")
                print(f"- {name} (type={ttype}, stream={stream})")
    except json.JSONDecodeError:
        print("- (unparsed)")

    print()
    print("Raw JSON:")
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
