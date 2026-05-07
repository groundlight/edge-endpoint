"""Captures host / driver / edge-endpoint metadata for summary.json."""

import hashlib
import logging
import platform
import subprocess
from typing import Any

import psutil
from groundlight import ExperimentalApi

import groundlight_helpers as glh

logger = logging.getLogger(__name__)


def _git_sha(path: str = ".") -> str | None:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, stderr=subprocess.DEVNULL)
        return sha.decode().strip()
    except Exception:
        return None


def _capture_host() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "kernel": platform.platform(),
        "cpu_model": platform.processor() or platform.machine(),
        "logical_cpus": psutil.cpu_count(logical=True),
        "ram_total_mb": int(vm.total / (1024 * 1024)),
    }


def _capture_gpus(resources: dict | None) -> tuple[list[dict], str]:
    if not resources or "error" in resources:
        return [], "unavailable"
    devices = resources.get("system", {}).get("gpu", {}).get("devices", []) or []
    out: list[dict] = []
    for d in devices:
        vram = d.get("vram_bytes", {}) or {}
        out.append({
            "index": d.get("index"),
            "uuid": d.get("uuid"),
            "name": d.get("name"),
            "vram_total_mb": int((vram.get("total") or 0) / (1024 * 1024)),
        })
    # Attribution: look for non-zero `other` buckets which indicate non-benchmark tenants.
    other_vram = (resources.get("system", {}).get("gpu", {}).get("vram_bytes", {}) or {}).get("other", 0) or 0
    other_compute = (resources.get("system", {}).get("gpu", {}).get("compute_utilization_pct", {}) or {}).get("other", 0) or 0
    attribution = "shared" if (other_vram > 0 or other_compute > 1) else "exclusive"
    return out, attribution


def _capture_edge_versions(gl_edge: ExperimentalApi) -> dict[str, str | None]:
    edge_image = inference_image = None
    try:
        edge_image, inference_image = glh.get_edge_and_inference_images(gl_edge)
    except Exception as exc:
        logger.debug("could not fetch edge container images: %s", exc)
    return {
        "edge_endpoint_image_digest": edge_image,
        "inference_server_image_digest": inference_image,
    }


def capture(gl_edge: ExperimentalApi, resources: dict | None, repo_root: str = ".") -> dict[str, Any]:
    gpus, attribution = _capture_gpus(resources)
    edge_versions = _capture_edge_versions(gl_edge)
    return {
        "host": _capture_host(),
        "gpus": gpus,
        "gpu_attribution": attribution,
        "harness_version": _git_sha(repo_root),
        **edge_versions,
    }


def hash_config_yaml(path: str) -> str:
    with open(path, "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()
