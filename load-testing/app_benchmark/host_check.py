"""Pre-flight: refuse to run if the edge has pre-existing non-bench detectors."""

import logging

from groundlight import ExperimentalApi

import groundlight_helpers as glh

logger = logging.getLogger(__name__)


class HostNotCleanError(RuntimeError):
    pass


def ensure_host_clean(gl_edge: ExperimentalApi, expected_prefix: str, *, allow: bool = False) -> None:
    """Hits /status/resources.json. Raises if any detectors[] entry has a name not starting with expected_prefix.

    If `allow=True`, only logs a warning instead of raising.
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

    foreign: list[str] = []
    for d in detectors:
        det_id = d.get("detector_id") or ""
        det_name = d.get("name") or det_id
        if not det_name.startswith(expected_prefix):
            foreign.append(f"{det_id} (name={det_name})")

    if not foreign:
        logger.info("host clean check passed — %d detector(s) loaded, all matching prefix %r",
                    len(detectors), expected_prefix, extra={"phase": "host_check"})
        return

    msg = (
        f"Edge has {len(foreign)} detector(s) not matching prefix {expected_prefix!r}: {foreign}. "
        f"Run on a clean instance, or set run.refuse_if_host_not_clean: false to override."
    )
    if allow:
        logger.warning("host clean check FAILED but allowed: %s", msg, extra={"phase": "host_check"})
    else:
        raise HostNotCleanError(msg)
