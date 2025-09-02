#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Generator, Optional

import requests


def get_namespace() -> str:
    ns = os.environ.get("DEPLOYMENT_NAMESPACE")
    if not ns:
        print("ERROR: DEPLOYMENT_NAMESPACE must be set (e.g., export DEPLOYMENT_NAMESPACE=edge)", file=sys.stderr)
        sys.exit(1)
    return ns


def kns(ns: str) -> list:
    return ["-n", ns]


def run(cmd: list, check: bool = False, capture_output: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=capture_output, text=True)


def manifest_path() -> str:
    # Use the YAML colocated with the python scripts
    return str((Path(__file__).resolve().parent / "k8s-toxiproxy.yaml").resolve())


def service_exists(name: str, ns: str) -> bool:
    return run(["kubectl", "get", "svc", name, *kns(ns)], check=False).returncode == 0


def wait_for_deploy_available(name: str, ns: str, timeout: str = "90s") -> None:
    run(
        [
            "kubectl",
            "wait",
            *kns(ns),
            "--for=condition=Available",
            f"deploy/{name}",
            f"--timeout={timeout}",
        ],
        check=True,
    )


def namespace_exists(ns: str) -> bool:
    return run(["kubectl", "get", "ns", ns], check=False).returncode == 0


def require_namespace_exists(ns: str) -> None:
    if not namespace_exists(ns):
        print(
            f"ERROR: Namespace '{ns}' does not exist. Please create it before enabling Toxiproxy.",
            file=sys.stderr,
        )
        sys.exit(1)


@contextmanager
def port_forward_service(
    ns: str,
    service: str = "toxiproxy",
    local_port: int = 8474,
    remote_port: int = 8474,
    timeout_sec: int = 15,
) -> Generator[str, None, None]:
    cmd = [
        "kubectl",
        "port-forward",
        f"--namespace={ns}",
        f"svc/{service}",
        f"{local_port}:{remote_port}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    base_url = f"http://127.0.0.1:{local_port}"
    try:
        # Wait for readiness
        start = time.time()
        while True:
            if proc.poll() is not None:
                raise RuntimeError("kubectl port-forward exited early")
            try:
                r = requests.get(f"{base_url}/version", timeout=1)
                if r.ok:
                    break
            except requests.RequestException:
                pass
            if time.time() - start > timeout_sec:
                raise TimeoutError("Timed out waiting for port-forward readiness")
            time.sleep(0.3)
        yield base_url
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


def http_request(method: str, url: str, json_body: Optional[Dict] = None, timeout: float = 5.0) -> requests.Response:
    method = method.upper()
    if method == "GET":
        return requests.get(url, timeout=timeout)
    if method == "POST":
        return requests.post(url, json=json_body, timeout=timeout)
    if method == "DELETE":
        return requests.delete(url, timeout=timeout)
    if method == "PUT":
        return requests.put(url, json=json_body, timeout=timeout)
    raise ValueError(f"Unsupported method: {method}")


def sleep_ms(ms: int) -> None:
    """Sleep for the specified duration in milliseconds. Negative values are treated as 0."""
    time.sleep(max(ms, 0) / 1000.0)
