"""Pre-flight: refuse to run if the edge has pre-existing detectors configured.

Source of truth is `gl.edge.get_config()` (vs /status/resources.json which only
shows pods that are actively reporting). To recover from a leak:

    python -m app_benchmark.cleanup_edge --edge-endpoint <URL> --wipe
"""

import logging

from groundlight import ExperimentalApi

logger = logging.getLogger(__name__)


class HostNotCleanError(RuntimeError):
    pass


def ensure_host_clean(gl_edge: ExperimentalApi, *, allow: bool = False) -> None:
    """Raise HostNotCleanError if any detector is configured on the edge.
    With `allow=True`, log a loud warning and proceed."""
    try:
        edge_config = gl_edge.edge.get_config()
    except Exception as exc:
        logger.warning("host clean check skipped — could not fetch edge config: %s", exc)
        return

    det_entries = getattr(edge_config, "detectors", None) or []
    det_ids = [d.detector_id for d in det_entries if hasattr(d, "detector_id")]
    if not det_ids:
        logger.info("host clean check passed — no detectors configured")
        return

    if allow:
        bar = "=" * 78
        logger.warning(bar)
        logger.warning("HOST NOT CLEAN — %d pre-existing detector(s) on the edge:", len(det_ids))
        for det_id in det_ids:
            logger.warning("    %s", det_id)
        logger.warning("These share GPU/CPU/RAM with the benchmark and WILL skew numbers.")
        logger.warning(bar)
        return

    raise HostNotCleanError(
        f"Edge has {len(det_ids)} pre-existing detector(s) configured: {det_ids}. "
        f"Wipe with: python -m app_benchmark.cleanup_edge --edge-endpoint <URL> --wipe. "
        f"Or set run.refuse_if_host_not_clean: false in the YAML to proceed (results will skew)."
    )
