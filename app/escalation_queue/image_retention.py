import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.escalation_queue.constants import (
    DEFAULT_QUEUE_BASE_DIR,
    IMAGE_DIR_SUFFIX,
    READING_DIR_SUFFIX,
    WRITING_DIR_SUFFIX,
)
from app.escalation_queue.failed_escalations import FAILED_ESCALATION_RETENTION_DAYS

logger = logging.getLogger(__name__)

IMAGE_DIR = Path(DEFAULT_QUEUE_BASE_DIR) / IMAGE_DIR_SUFFIX
# Directories holding queue entries that reference images which have not yet been consumed.
QUEUE_ENTRY_DIRS = (
    Path(DEFAULT_QUEUE_BASE_DIR) / WRITING_DIR_SUFFIX,
    Path(DEFAULT_QUEUE_BASE_DIR) / READING_DIR_SUFFIX,
)


def _collect_referenced_image_paths() -> set[str]:
    """Return the set of resolved image paths still referenced by queued (unconsumed) escalations."""
    referenced: set[str] = set()
    for base in QUEUE_ENTRY_DIRS:
        if not base.exists():
            continue
        for path in base.glob("*.txt"):
            try:
                with path.open("r") as f:
                    for line in f:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            data = json.loads(stripped)
                        except Exception:
                            # A malformed line (or a tracking file) yields no recoverable image reference;
                            # any image it points to is treated as an orphan and left to the age check.
                            continue
                        image_path_str = data.get("image_path_str")
                        if isinstance(image_path_str, str) and image_path_str:
                            referenced.add(str(Path(image_path_str).resolve()))
            except FileNotFoundError:
                # The reader renamed/consumed the file between glob and open. Benign: it will be seen in
                # the other queue dir on this pass or has already been fully processed.
                continue
            except OSError:
                logger.warning(f"Could not read queue file {path}; treating its images as unreferenced.", exc_info=True)
                continue
    return referenced


def prune_orphaned_images() -> None:
    """Delete unreferenced escalation images older than the retention window."""
    if not IMAGE_DIR.exists():
        return

    referenced = _collect_referenced_image_paths()

    cutoff = datetime.now(timezone.utc) - timedelta(days=FAILED_ESCALATION_RETENTION_DAYS)
    for path in IMAGE_DIR.iterdir():
        try:
            if not path.is_file():
                continue
            if str(path.resolve()) in referenced:
                continue  # Still referenced by a queued escalation; must not delete.
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                path.unlink(missing_ok=True)
        except Exception:
            logger.debug(f"Failed to prune orphaned image {path}", exc_info=True)
