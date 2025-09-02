#!/usr/bin/env python3
import sys

from common import get_namespace, kns, manifest_path, run


def main() -> int:
    ns = get_namespace()

    print("[1/3] Removing hostAliases from edge-endpoint Deployment (if present)")
    run(
        [
            "kubectl",
            "patch",
            "deploy",
            "edge-endpoint",
            *kns(ns),
            "--type",
            "json",
            "-p",
            '[{"op":"remove","path":"/spec/template/spec/hostAliases"}]',
        ],
        check=False,
    )

    print("[2/3] Deleting Toxiproxy resources")
    run(["kubectl", "delete", *kns(ns), "-f", str(manifest_path()), "--ignore-not-found"], check=False)

    print("[3/3] Waiting for edge-endpoint rollout")
    run(["kubectl", "rollout", "restart", "deploy/edge-endpoint", *kns(ns)], check=True)
    run(["kubectl", "rollout", "status", "deploy/edge-endpoint", *kns(ns), "--timeout=120s"], check=True)

    print("Done. Traffic is no longer routed through Toxiproxy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
