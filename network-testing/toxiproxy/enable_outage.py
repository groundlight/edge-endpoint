#!/usr/bin/env python3
import sys

from common import get_namespace, port_forward_service, post_proxy_method, require_toxiproxy_installed
from fastapi import status


def main() -> int:
    ns = get_namespace()

    require_toxiproxy_installed(ns, exit_code=1)

    with port_forward_service(ns) as base_url:
        status_code = post_proxy_method(base_url, "", {"enabled": False})
        if status_code in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
            print("Outage enabled: proxy disabled (connections will be refused).")
            return 0
        else:
            print(f"Failed to disable proxy. HTTP {status_code}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
