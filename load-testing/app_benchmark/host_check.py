"""Pre-flight: refuse to run if the edge has pre-existing detectors configured.

Source of truth is `gl.edge.get_config()` (vs /status/resources.json which only
shows pods that are actively reporting). To recover from a leak:

    python -m app_benchmark.cleanup_edge --edge-endpoint <URL> --wipe
"""

import logging

from groundlight import ExperimentalApi

logger = logging.getLogger(__name__)


class HostNotCleanError(RuntimeError):
    """Raised by ensure_host_clean when the edge already has detectors
    configured and refuse_if_host_not_clean is True."""


def ensure_host_clean(gl_edge: ExperimentalApi, *, allow: bool = False) -> None:
    """Pre-flight check: warn or refuse when the edge has pre-existing detectors.

    The benchmark pushes an edge config containing ONLY its own
    detectors, so any pre-existing detectors get evicted (their pods
    torn down) for the duration of the run and restored at cleanup.
    That keeps the measurement clean but means any application using
    those detectors will see errors until cleanup completes.

    Args:
        gl_edge: SDK client pointed at the local edge endpoint.
        allow: If True, downgrade the failure to a loud warning and
            proceed (eviction + restore at cleanup). Controlled from
            YAML via `run.refuse_if_host_not_clean: false`.

    Raises:
        HostNotCleanError: When `allow=False` and the edge has ≥1
            detector configured. Message includes the recovery command
            (cleanup_edge.py --wipe) and the YAML flag to bypass.
    """
    try:
        edge_config = gl_edge.edge.get_config()
    except Exception as exc:
        logger.warning("host clean check skipped — could not fetch edge config: %s", exc)
        return

    det_entries = getattr(edge_config, "detectors", None) or []
    det_ids = [d.detector_id for d in det_entries]
    if not det_ids:
        logger.info("host clean check passed — no detectors configured")
        return

    if allow:
        bar = "=" * 78
        logger.warning(bar)
        logger.warning("HOST NOT CLEAN — %d pre-existing detector(s) on the edge:", len(det_ids))
        for det_id in det_ids:
            logger.warning("    %s", det_id)
        logger.warning("These will be TEMPORARILY EVICTED while the benchmark runs and")
        logger.warning("RESTORED at cleanup. Applications that depend on them will see")
        logger.warning("errors for the duration of the run, plus cold-start latency")
        logger.warning("once they come back up.")
        logger.warning(bar)
        return

    raise HostNotCleanError(
        f"Edge has {len(det_ids)} pre-existing detector(s) configured: {det_ids}. "
        f"Set run.refuse_if_host_not_clean: false in the YAML to proceed — those "
        f"detectors will be temporarily evicted for the duration of the benchmark "
        f"and restored at cleanup. Or wipe them manually with: "
        f"python -m app_benchmark.cleanup_edge --edge-endpoint <URL> --wipe."
    )
