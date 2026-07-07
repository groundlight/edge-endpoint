import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.escalation_queue.constants import (
    DEFAULT_QUEUE_BASE_DIR,
    IMAGE_DIR_SUFFIX,
    READING_DIR_SUFFIX,
    WRITING_DIR_SUFFIX,
)
from app.escalation_queue.failed_escalations import FAILED_ESCALATIONS_DIR

logger = logging.getLogger(__name__)

QUEUE_RETENTION_DAYS = 7

# Every directory the escalation queue writes to disk. Anything older than the retention window is
# deleted regardless of escalation status: stale pending escalations, their images, and failed-
# escalation records alike.
RETENTION_DIRS = (
    Path(DEFAULT_QUEUE_BASE_DIR) / IMAGE_DIR_SUFFIX,
    Path(DEFAULT_QUEUE_BASE_DIR) / WRITING_DIR_SUFFIX,
    Path(DEFAULT_QUEUE_BASE_DIR) / READING_DIR_SUFFIX,
    FAILED_ESCALATIONS_DIR,
)


def prune_expired_queue_data() -> None:
    """Delete queued escalation data and images older than QUEUE_RETENTION_DAYS.

    Enforces a hard data-retention bound on everything the escalation queue writes to disk. Deletion is
    purely age-based (by mtime) and applies regardless of escalation status, so stale pending
    escalations are dropped along with orphaned images and failed-escalation records once past the
    window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=QUEUE_RETENTION_DAYS)
    for base in RETENTION_DIRS:
        if not base.exists():
            continue
        for path in base.iterdir():
            try:
                if not path.is_file():
                    continue
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    path.unlink(missing_ok=True)
            except Exception:
                logger.debug(f"Failed to prune expired queue file {path}", exc_info=True)
