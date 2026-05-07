"""Post-`set_config` control-plane verification.

Asserts:
  1. gl.ask_ml with a sentinel image returns from_edge=True per detector.
  2. gl.edge.get_detector_readiness() shows all our detectors as ready (=True).
  3. Sentinel latency is below the sanity threshold (slower implies cloud fallback).
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
from groundlight import Detector, ExperimentalApi

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
            readiness = self.gl_edge.edge.get_detector_readiness()
        except Exception as exc:
            raise VerificationError(f"get_detector_readiness failed: {exc}") from exc
        missing = expected_ids - set(readiness.keys())
        if missing:
            raise VerificationError(f"expected detector(s) not configured on edge: {sorted(missing)}")
        not_ready = sorted(did for did in expected_ids if not readiness.get(did, False))
        if not_ready:
            raise VerificationError(f"detector(s) not ready (inference pods still loading): {not_ready}")

    def _check_sentinel(self, detectors: list[Detector]) -> None:
        for det in detectors:
            t0 = time.perf_counter()
            # ask_ml: ML-only prediction, no cloud poll for confidence — required in NO_CLOUD mode.
            iq = self.gl_edge.ask_ml(det, self._sentinel_image)
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
            self.gl_edge.ask_ml(det, self._sentinel_image)
            latencies[det.id] = (time.perf_counter() - t0) * 1000
        return latencies
