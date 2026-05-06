"""Pre-flight: refuse to run if the edge has pre-existing detectors loaded.

The /status/resources.json detectors[] entries only carry `detector_id` (no
cloud `name`), so we can't prefix-match here. Policy: a "clean host" has zero
loaded detectors. To recover from a leak, use:

    python -m app_benchmark.cleanup_edge --edge-endpoint <URL> --wipe
"""

import logging

from groundlight import ExperimentalApi

import groundlight_helpers as glh

logger = logging.getLogger(__name__)


class HostNotCleanError(RuntimeError):
    pass


def ensure_host_clean(gl_edge: ExperimentalApi, expected_prefix: str, *, allow: bool = False) -> None:
    """Hits /status/resources.json. Raises if ANY detector is loaded on the edge.

    `expected_prefix` is accepted for forward compatibility (so the harness can
    match cloud-name prefixes once the resource endpoint returns names) but is
    not currently used for matching. With `allow=True`, prints a loud warning
    and proceeds.
    """
    try:
        resources = glh._get_resources(gl_edge, timeout=5.0)
    except Exception as exc:
        logger.warning("host clean check skipped — could not fetch /status/resources.json: %s", exc,
                       extra={"phase": "host_check"})
        return

    if "error" in resources:
        logger.warning("host clean check skipped — resource collector returned error: %s",
                       resources.get("error"), extra={"phase": "host_check"})
        return

    detectors = resources.get("detectors", []) or []
    if not detectors:
        logger.info("host clean check passed — no detectors loaded", extra={"phase": "host_check"})
        return

    det_ids = [d.get("detector_id") or "<no-id>" for d in detectors]

    if allow:
        bar = "=" * 78
        logger.warning(bar, extra={"phase": "host_check"})
        logger.warning("HOST NOT CLEAN — %d pre-existing detector(s) on the edge:",
                       len(det_ids), extra={"phase": "host_check"})
        for det_id in det_ids:
            logger.warning("    %s", det_id, extra={"phase": "host_check"})
        logger.warning("These detectors share GPU/CPU/RAM with the benchmark and WILL affect the",
                       extra={"phase": "host_check"})
        logger.warning("FPS / VRAM / latency numbers. Re-run on a clean edge for trustworthy results.",
                       extra={"phase": "host_check"})
        logger.warning(bar, extra={"phase": "host_check"})
        return

    msg = (
        f"Edge has {len(det_ids)} pre-existing detector(s) loaded: {det_ids}. "
        f"Wipe with: python -m app_benchmark.cleanup_edge --edge-endpoint <URL> --wipe. "
        f"Or set run.refuse_if_host_not_clean: false in the YAML to proceed with a "
        f"contaminated host (results will be affected)."
    )
    raise HostNotCleanError(msg)
