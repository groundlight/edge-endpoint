#!/usr/bin/env python3
import json
import sys

from common import (
    get_namespace,
    http_request,
    kns,
    manifest_path,
    port_forward_service,
    require_namespace_exists,
    run,
    wait_for_deploy_available,
)


def main() -> int:
    ns = get_namespace()

    print(f"[1/5] Checking namespace exists: {ns}")
    require_namespace_exists(ns)

    print("[2/5] Deploying Toxiproxy")
    run(["kubectl", "apply", *kns(ns), "-f", str(manifest_path())], check=True)

    print("[3/5] Waiting for Toxiproxy pod to be Ready")
    wait_for_deploy_available("toxiproxy", ns, timeout="90s")

    print("[4/5] Creating/Updating Toxiproxy proxy for api.groundlight.ai:443")
    with port_forward_service(ns) as base_url:
        # Create proxy if missing; ignore errors if exists
        http_request(
            "POST",
            f"{base_url}/proxies",
            {
                "name": "api_groundlight_ai",
                "listen": "0.0.0.0:10443",
                "upstream": "api.groundlight.ai:443",
                "enabled": True,
            },
        )
        # Update proxy definition (idempotent)
        resp = http_request(
            "POST",
            f"{base_url}/proxies/api_groundlight_ai",
            {"upstream": "api.groundlight.ai:443", "enabled": True},
        )
        if resp.status_code not in {200, 201}:
            print(f"Warning: updating proxy returned HTTP {resp.status_code}")

    print("[5/5] Patching edge-endpoint Deployment hostAliases to direct api.groundlight.ai to Toxiproxy")
    cp = run(["kubectl", "get", "svc", "toxiproxy", *kns(ns), "-o", "jsonpath={.spec.clusterIP}"], check=True)
    svc_ip = cp.stdout.strip()
    patch = json.dumps(
        {"spec": {"template": {"spec": {"hostAliases": [{"ip": svc_ip, "hostnames": ["api.groundlight.ai"]}]}}}}
    )
    run(
        [
            "kubectl",
            "patch",
            "deploy",
            "edge-endpoint",
            *kns(ns),
            "--type",
            "merge",
            "-p",
            patch,
        ],
        check=True,
    )

    print("Waiting for rollout to complete...")
    run(["kubectl", "rollout", "status", "deploy/edge-endpoint", *kns(ns), "--timeout=120s"], check=True)

    print("Done enabling Toxiproxy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
