"""Pre-flight: refuse to run if the edge has pre-existing detectors configured.

Reads the active edge config via `gl.edge.get_config()` — that's the source
of truth for what's configured (vs. /status/resources.json which only shows
detectors whose pods are actively reporting). To recover from a leak:

    python -m app_benchmark.cleanup_edge --edge-endpoint <URL> --wipe
"""

import logging

from groundlight import ExperimentalApi

logger = logging.getLogger(__name__)


class HostNotCleanError(RuntimeError):
    pass


def ensure_host_clean(gl_edge: ExperimentalApi, expected_prefix: str, *, allow: bool = False) -> None:
    """Reads gl.edge.get_config() and refuses if ANY detector is configured.

    `expected_prefix` is accepted for forward compatibility but not used.
    With `allow=True`, prints a loud warning and proceeds.
    """
    try:
        edge_config = gl_edge.edge.get_config()
    except Exception as exc:
        logger.warning("host clean check skipped — could not fetch edge config: %s", exc,
                       extra={"phase": "host_check"})
        return

    det_entries = getattr(edge_config, "detectors", None) or []
    det_ids = [d.detector_id for d in det_entries if hasattr(d, "detector_id")]

    if not det_ids:
        logger.info("host clean check passed — no detectors configured",
                    extra={"phase": "host_check"})
        return

    if allow:
        bar = "=" * 78
        logger.warning(bar, extra={"phase": "host_check"})
        logger.warning("HOST NOT CLEAN — %d pre-existing detector(s) configured on the edge:",
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
        f"Edge has {len(det_ids)} pre-existing detector(s) configured: {det_ids}. "
        f"Wipe with: python -m app_benchmark.cleanup_edge --edge-endpoint <URL> --wipe. "
        f"Or set run.refuse_if_host_not_clean: false in the YAML to proceed with a "
        f"contaminated host (results will be affected)."
    )
    raise HostNotCleanError(msg)
