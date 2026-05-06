"""Post-`set_config` control-plane verification.

Asserts:
  1. POST /image-queries with a sentinel image returns from_edge=True per detector.
  2. /status/resources.json shows our created detectors and loading_detectors == 0.
  3. Sentinel latency is below the sanity threshold (slower implies cloud fallback).
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
from groundlight import Detector, ExperimentalApi

import groundlight_helpers as glh

logger = logging.getLogger(__name__)

LATENCY_SANITY_THRESHOLD_S = 5.0
DEFAULT_TIMEOUT_S = 120
POLL_INTERVAL_S = 2.0


class VerificationError(RuntimeError):
    pass


@dataclass
class VerificationResult:
    from_edge_verified: bool
    introspection_used: bool
    loaded_detector_ids: set[str]
    sentinel_latency_ms: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class Verifier:
    def __init__(self, gl_edge: ExperimentalApi, sentinel_image_path: str | Path) -> None:
        self.gl_edge = gl_edge
        path = Path(sentinel_image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Sentinel image not found: {sentinel_image_path}")
        self._sentinel_path = path
        self._sentinel_image = cv2.imread(str(path))
        if self._sentinel_image is None:
            raise RuntimeError(f"Could not decode sentinel image: {sentinel_image_path}")

    def wait_for_ready(self, detectors: list[Detector], timeout_s: float = DEFAULT_TIMEOUT_S) -> VerificationResult:
        deadline = time.time() + timeout_s
        expected_ids = {d.id for d in detectors}
        last_error: str | None = None

        while time.time() < deadline:
            try:
                self._check_resources_loaded(expected_ids)
                self._check_sentinel(detectors)
            except VerificationError as exc:
                last_error = str(exc)
                logger.info("readiness check not yet satisfied: %s", exc, extra={"phase": "verification"})
                time.sleep(POLL_INTERVAL_S)
                continue
            break
        else:
            raise VerificationError(f"Readiness verification timed out after {timeout_s}s: {last_error}")

        latencies = self._final_sentinel_pass(detectors)
        return VerificationResult(
            from_edge_verified=True,
            introspection_used=True,
            loaded_detector_ids=expected_ids,
            sentinel_latency_ms=latencies,
        )

    def _check_resources_loaded(self, expected_ids: set[str]) -> None:
        try:
            resources = glh._get_resources(self.gl_edge, timeout=5.0)
        except Exception as exc:
            raise VerificationError(f"resource fetch failed: {exc}") from exc
        if "error" in resources:
            raise VerificationError(f"resource endpoint reported error: {resources.get('error')}")
        loading = resources.get("system", {}).get("gpu", {}).get("vram_bytes", {}).get("loading_detectors", 0)
        if loading and loading > 0:
            raise VerificationError(f"detectors still loading (loading_detectors={loading} bytes)")
        loaded = {d.get("detector_id") for d in resources.get("detectors", []) or []}
        missing = expected_ids - loaded
        if missing:
            raise VerificationError(f"expected detector(s) not present in /status/resources.json: {sorted(missing)}")

    def _check_sentinel(self, detectors: list[Detector]) -> None:
        for det in detectors:
            t0 = time.perf_counter()
            iq = self.gl_edge.submit_image_query(det, self._sentinel_image, **glh.IQ_KWARGS_FOR_NO_ESCALATION)
            elapsed = time.perf_counter() - t0
            if elapsed > LATENCY_SANITY_THRESHOLD_S:
                raise VerificationError(
                    f"sentinel latency for {det.id} = {elapsed:.2f}s exceeds threshold {LATENCY_SANITY_THRESHOLD_S}s "
                    f"(possible cloud fallback)"
                )
            if not iq.result or not getattr(iq.result, "from_edge", False):
                raise VerificationError(f"sentinel response for {det.id} did not have from_edge=True")

    def _final_sentinel_pass(self, detectors: list[Detector]) -> dict[str, float]:
        latencies: dict[str, float] = {}
        for det in detectors:
            t0 = time.perf_counter()
            self.gl_edge.submit_image_query(det, self._sentinel_image, **glh.IQ_KWARGS_FOR_NO_ESCALATION)
            latencies[det.id] = (time.perf_counter() - t0) * 1000
        return latencies
