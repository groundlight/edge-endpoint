"""Shared cloud-escalation cooldown for every uvicorn worker.

Each detector has one timestamp file under the device hostPath. Reserving the next
escalation takes an exclusive lock on that file, writes the new timestamp, and
returns. The queue write happens after the lock is released. Eight worker processes
therefore enforce one min_time_between_escalations interval instead of one each.
"""

import fcntl
import logging
import os
import re
import time

from app.core import file_paths

logger = logging.getLogger(__name__)

# Same shape as DetectorConfig.detector_id. The id is the filename, so it must not be a path.
_DETECTOR_ID_RE = re.compile(r"^det_[A-Za-z0-9]{27}$")


def reserve_escalation_if_cooldown_elapsed(
    detector_id: str, min_interval_sec: float, directory: str | None = None
) -> bool:
    """Start the cooldown and return True when this caller may escalate.

    The timestamp write is visible to every process on this machine. Returns False,
    without writing, when the last reservation was within min_interval_sec or when
    the timestamp cannot be saved. The caller escalates after this returns.
    """
    if _DETECTOR_ID_RE.fullmatch(detector_id) is None:
        logger.error("Refusing escalation cooldown reservation for unexpected detector id %r", detector_id)
        return False

    cooldown_dir = file_paths.ESCALATION_COOLDOWN_DIR if directory is None else directory
    path = os.path.join(cooldown_dir, detector_id)
    try:
        os.makedirs(cooldown_dir, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        logger.exception("Failed to open escalation cooldown file for %s", detector_id)
        return False

    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            return _reserve_while_locked(fd, min_interval_sec, detector_id)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        logger.exception("Failed to update escalation cooldown file for %s", detector_id)
        return False
    finally:
        os.close(fd)


def _reserve_while_locked(fd: int, min_interval_sec: float, detector_id: str) -> bool:
    """Write the timestamp and return True if the cooldown has elapsed. Caller holds the lock."""
    raw = os.read(fd, 128)
    last = _parse_timestamp(raw)
    now = time.time()
    if last is not None and (now - last) <= min_interval_sec:
        return False
    if raw.strip() and last is None:
        logger.warning("Replacing unreadable escalation cooldown timestamp for %s", detector_id)
    payload = f"{now:.6f}\n".encode("ascii")
    os.lseek(fd, 0, os.SEEK_SET)
    written = os.write(fd, payload)
    if written != len(payload):
        raise OSError(f"Short write to escalation cooldown file for {detector_id}")
    os.ftruncate(fd, len(payload))
    os.fsync(fd)
    return True


def _parse_timestamp(raw: bytes) -> float | None:
    """Return the timestamp stored in a cooldown file, or None if it is empty or corrupt."""
    text = raw.decode("ascii", errors="replace").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
