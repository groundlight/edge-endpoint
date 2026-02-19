import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import ksuid

from app.escalation_queue.constants import DEFAULT_QUEUE_BASE_DIR

logger = logging.getLogger(__name__)

FAILED_ESCALATIONS_DIR = Path(DEFAULT_QUEUE_BASE_DIR) / "failed"
MAX_RECORDS = 200
MAX_EXCEPTION_MESSAGE_CHARS = 1000
MAX_TRACEBACK_CHARS = 4000  # Caps exception tracebacks in failure records
MAX_ESCALATION_CHARS = 4000  # Caps raw (malformed) escalation payloads in failure records


def _ensure_dir_exists() -> None:
    """Ensure the failed-escalations directory exists."""
    FAILED_ESCALATIONS_DIR.mkdir(parents=True, exist_ok=True)


def _truncate(text: str | None, max_chars: int) -> str | None:
    """Return a string truncated to at most `max_chars` characters."""
    if text is None:
        return None
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]...\n"


def _format_traceback(exc: Exception, max_chars: int) -> str | None:
    """Format an exception traceback and truncate it to a maximum length."""
    try:
        tb = "".join(traceback.format_exception(exc))
    except Exception:
        return None
    return _truncate(tb, max_chars)


def _parse_escalation(value: str | None, max_chars: int) -> tuple[str, Any]:
    """Parse a queued escalation line as JSON or preserve it as raw text."""
    if value is None:
        return "none", None
    stripped = value.strip()
    if not stripped:
        return "none", None
    try:
        return "json", json.loads(stripped)
    except Exception:
        return "raw", _truncate(value, max_chars)


def record_failed_escalation(escalation_line: str | None, exc: Exception) -> None:
    """
    Records an escalation that permanently failed or was skipped due to an exception.

    The record is written as a single JSON file under the local failed-escalations directory.
    """
    try:
        _ensure_dir_exists()

        now = datetime.now(timezone.utc)
        record_id = str(ksuid.KsuidMs())
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        record_path = FAILED_ESCALATIONS_DIR / f"{timestamp}-{record_id}.json"
        tmp_path = record_path.with_suffix(".json.tmp")

        escalation_format, escalation = _parse_escalation(escalation_line, max_chars=MAX_ESCALATION_CHARS)

        record = {
            "id": record_id,
            "recorded_at": now.isoformat(),
            "escalation_format": escalation_format,
            "escalation": escalation,
            "exception_type": type(exc).__name__,
            "exception_message": _truncate(str(exc), MAX_EXCEPTION_MESSAGE_CHARS),
            "traceback": _format_traceback(exc, max_chars=MAX_TRACEBACK_CHARS),
        }

        tmp_path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        tmp_path.replace(record_path)

        prune_failed_escalations()
    except Exception as ex:
        logger.error(f"Failed to record failed escalation: {ex}", exc_info=True)


def prune_failed_escalations() -> None:
    """Apply retention limits and cleanup for failed-escalation record files."""
    _ensure_dir_exists()

    # Best-effort cleanup for crash leftovers from atomic record writes (write to `*.json.tmp`, then rename).
    for path in FAILED_ESCALATIONS_DIR.glob("*.json.tmp"):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.debug(f"Failed to remove temp file {path}", exc_info=True)

    files = sorted(FAILED_ESCALATIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime_ns)
    while len(files) > MAX_RECORDS:
        (files.pop(0)).unlink(missing_ok=True)


def metrics_summary() -> dict[str, Any]:
    """
    Summarizes failed escalations for status/metrics reporting.

    Reads from the local record files; keeps the payload small (counts + timestamps + exception breakdown).
    """
    _ensure_dir_exists()
    files = list(FAILED_ESCALATIONS_DIR.glob("*.json"))
    now = datetime.now(timezone.utc)
    last_hour_cutoff = now - timedelta(hours=1)

    last_failed_time: str | None = None
    failed_last_hour_total = 0
    failed_last_hour_by_exception: dict[str, int] = {}

    def _as_dt(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except Exception:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    newest_dt: datetime | None = None
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        recorded_at = _as_dt(data.get("recorded_at"))
        if recorded_at is None:
            continue

        if newest_dt is None or recorded_at > newest_dt:
            newest_dt = recorded_at

        exc_type = data.get("exception_type")
        if recorded_at >= last_hour_cutoff and isinstance(exc_type, str) and exc_type:
            failed_last_hour_total += 1
            failed_last_hour_by_exception[exc_type] = failed_last_hour_by_exception.get(exc_type, 0) + 1

    if newest_dt is not None:
        last_failed_time = newest_dt.isoformat()

    return {
        "activity_hour": last_hour_cutoff.strftime("%Y-%m-%d_%H"),
        "last_failed_time": last_failed_time,
        "failed_last_hour_total": failed_last_hour_total,
        # Stringify to avoid dynamic keys being indexed in OpenSearch.
        "failed_last_hour_by_exception": json.dumps(failed_last_hour_by_exception, sort_keys=True),
    }
