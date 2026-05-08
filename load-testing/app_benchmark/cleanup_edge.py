"""Standalone CLI to inspect / wipe the edge-endpoint's loaded detector config.

Companion to cleanup_orphans.py (cloud-side). Useful when a previous run leaked
detectors on the edge (SIGKILL, OOM, etc.).

    python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --list
    python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe
"""

import argparse
import logging
import sys

from groundlight import ExperimentalApi
from groundlight.edge import EdgeEndpointConfig

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edge-endpoint", required=True, help="Edge endpoint URL.")
    parser.add_argument("--list", action="store_true", help="Print currently-loaded detectors and exit.")
    parser.add_argument("--wipe", action="store_true", help="Push an empty EdgeEndpointConfig.")
    parser.add_argument("--confirm", action="store_true", help="With --wipe, require interactive confirmation.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not args.list and not args.wipe:
        parser.error("must pass at least one of --list, --wipe")

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

    if args.list and not args.wipe:
        return 0
    if not det_ids:
        logger.info("Nothing to wipe.")
        return 0
    if args.confirm:
        ans = input(f"Wipe {len(det_ids)} detector(s) from {args.edge_endpoint}? [y/N] ").strip().lower()
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
