"""Standalone CLI to inspect or wipe the edge-endpoint's loaded detector config.

Useful when a previous run leaked detectors on the edge (SIGKILL, OOM, etc.).
Without flags, lists what's currently configured. With `--wipe`, pushes an
empty config (asks for confirmation unless `--force` is passed).

    # list (default)
    python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101

    # wipe with confirmation
    python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe

    # wipe without confirmation (scripted use)
    python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe --force
"""

import argparse
import logging
import sys

from groundlight import ExperimentalApi
from groundlight.edge import EdgeEndpointConfig

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: list and/or wipe the edge endpoint's configured detectors.

    Useful after a hard kill (SIGKILL/OOM) when the benchmark's atexit
    handler didn't run and inference pods are still loaded on the edge.

    Args:
        argv: Optional CLI args list (None means use sys.argv).

    Returns:
        Exit code: 0 success, 1 wipe failed or user aborted at confirm,
        2 could not reach edge.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edge-endpoint", required=True, help="Edge endpoint URL.")
    parser.add_argument("--wipe", action="store_true",
                        help="Push an empty EdgeEndpointConfig (asks for confirmation).")
    parser.add_argument("--force", action="store_true",
                        help="With --wipe, skip the interactive confirmation prompt.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    gl = ExperimentalApi(endpoint=args.edge_endpoint)
    try:
        current = gl.edge.get_config()
    except Exception as exc:
        logger.error("could not fetch current edge config: %s", exc)
        return 2

    det_entries = getattr(current, "detectors", None) or []
    det_ids = [d.detector_id for d in det_entries if hasattr(d, "detector_id")]
    logger.info("Edge has %d detector(s) configured:", len(det_ids))
    for det_id in det_ids:
        logger.info("  - %s", det_id)

    if not args.wipe:
        return 0
    if not det_ids:
        logger.info("Nothing to wipe.")
        return 0
    if not args.force:
        ans = input(
            f"Wipe {len(det_ids)} detector(s) from {args.edge_endpoint}? [y/N] "
        ).strip().lower()
        if ans != "y":
            logger.info("aborted")
            return 1

    try:
        gl.edge.set_config(EdgeEndpointConfig())
        logger.info("edge config wiped (empty config pushed)")
        return 0
    except Exception as exc:
        logger.error("failed to wipe edge config: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
