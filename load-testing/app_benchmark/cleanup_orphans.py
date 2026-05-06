"""Standalone CLI to delete orphan detectors (e.g. after SIGKILL leak).

Usage:
    python -m app_benchmark.cleanup_orphans --prefix bench [--cloud-endpoint URL] [--dry-run]
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from groundlight import ExperimentalApi

logger = logging.getLogger(__name__)

_MIN_PREFIX_LEN = 4


def _parse_age(s: str | None) -> timedelta | None:
    if not s:
        return None
    s = s.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if s[-1] in units:
        try:
            value = float(s[:-1])
            return timedelta(seconds=value * units[s[-1]])
        except ValueError:
            pass
    raise ValueError(f"could not parse --older-than: {s!r} (try formats like '1h', '30m', '2d')")


def _list_all_detectors(gl: ExperimentalApi):
    page = 1
    page_size = 100
    while True:
        page_obj = gl.list_detectors(page=page, page_size=page_size)
        results = getattr(page_obj, "results", None) or []
        for d in results:
            yield d
        if len(results) < page_size:
            return
        page += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, help="Detector name prefix to match (e.g. 'bench').")
    parser.add_argument("--older-than", default=None,
                        help="Only delete detectors created at least this long ago (e.g. '1h', '2d').")
    parser.add_argument("--cloud-endpoint", default=None, help="Override the Groundlight cloud endpoint URL.")
    parser.add_argument("--dry-run", action="store_true", help="List intended deletions; do not delete.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.prefix or len(args.prefix) < _MIN_PREFIX_LEN:
        logger.error("--prefix must be at least %d characters; refusing to act on %r",
                     _MIN_PREFIX_LEN, args.prefix)
        return 2

    try:
        age_threshold = _parse_age(args.older_than)
    except ValueError as exc:
        logger.error(str(exc))
        return 2

    if not os.environ.get("GROUNDLIGHT_API_TOKEN"):
        logger.error("GROUNDLIGHT_API_TOKEN environment variable is not set.")
        return 2

    gl = ExperimentalApi(endpoint=args.cloud_endpoint) if args.cloud_endpoint else ExperimentalApi()

    now = datetime.now(timezone.utc)
    targeted: list[tuple[str, str]] = []

    for det in _list_all_detectors(gl):
        name = getattr(det, "name", "") or ""
        if not name.startswith(args.prefix):
            continue
        if age_threshold is not None:
            created_at = getattr(det, "created_at", None)
            if created_at is not None:
                try:
                    if isinstance(created_at, str):
                        created_at_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    else:
                        created_at_dt = created_at
                    if now - created_at_dt < age_threshold:
                        continue
                except Exception:
                    pass
        targeted.append((det.id, name))

    if not targeted:
        logger.info("No matching detectors found for prefix %r.", args.prefix)
        return 0

    logger.info("%s %d detector(s) matching prefix %r:",
                "Would delete" if args.dry_run else "Deleting", len(targeted), args.prefix)
    for det_id, name in targeted:
        logger.info("  - %s | %s", det_id, name)

    if args.dry_run:
        return 0

    failed = 0
    for det_id, name in targeted:
        try:
            gl.delete_detector(det_id)
            logger.info("deleted %s", det_id)
        except Exception as exc:
            failed += 1
            logger.error("failed to delete %s: %s", det_id, exc)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
