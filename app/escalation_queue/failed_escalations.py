import json
import logging
import os
import traceback
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import ksuid

from app.escalation_queue.constants import DEFAULT_QUEUE_BASE_DIR
from app.escalation_queue.models import EscalationInfo

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _base_dir() -> Path:
    return Path(os.environ.get("FAILED_ESCALATIONS_DIR", f"{DEFAULT_QUEUE_BASE_DIR}/failed"))


def _records_dir() -> Path:
    return _base_dir() / "records"


def _counters_dir() -> Path:
    return _base_dir() / "counters"


def _ensure_dirs() -> None:
    _records_dir().mkdir(parents=True, exist_ok=True)
    _counters_dir().mkdir(parents=True, exist_ok=True)


def _max_records() -> int:
    return int(os.environ.get("FAILED_ESCALATIONS_MAX_RECORDS", "200"))


def _max_bytes() -> int:
    return int(os.environ.get("FAILED_ESCALATIONS_MAX_BYTES", str(500 * 1024 * 1024)))


def _max_stacktrace_chars() -> int:
    return int(os.environ.get("FAILED_ESCALATIONS_MAX_STACKTRACE_CHARS", "8000"))


def _format_stacktrace(exc: BaseException) -> str | None:
    try:
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        return None

    max_chars = _max_stacktrace_chars()
    if max_chars <= 0:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]...\n"


def record_failed_escalation(
    escalation_line: str,
    exc: BaseException,
    *,
    status: str = "dropped",
) -> None:
    try:
        _ensure_dirs()

        now = datetime.now(timezone.utc)
        record_id = str(ksuid.KsuidMs())

        escalation_info = None
        raw_line = None
        try:
            escalation_info = EscalationInfo(**json.loads(escalation_line.strip()))
        except Exception:
            raw_line = escalation_line

        exception_type = type(exc).__name__
        exception_message = str(exc)
        retry_count = getattr(exc, "retry_count", None)
        stacktrace = _format_stacktrace(exc)

        _write_record(
            record_id=record_id,
            now=now,
            status=status,
            exception_type=exception_type,
            exception_message=exception_message,
            stacktrace=stacktrace,
            retry_count=retry_count,
            escalation_info=escalation_info,
            raw_line=raw_line,
        )

        _prune_records()
    except Exception as ex:
        logger.error(f"Failed to record failed escalation: {ex}", exc_info=True)


def record_failed_enqueue(*, escalation_info: EscalationInfo | None, exc: BaseException) -> None:
    """
    Records a failure while trying to enqueue an escalation (write image/line to the queue).

    Uses the same record format as `record_failed_escalation`, but avoids coupling queue-writing code
    to the escalation queue reader control flow.
    """
    try:
        _ensure_dirs()

        now = datetime.now(timezone.utc)
        record_id = str(ksuid.KsuidMs())

        exception_type = type(exc).__name__
        exception_message = str(exc)
        stacktrace = _format_stacktrace(exc)

        _write_record(
            record_id=record_id,
            now=now,
            status="dropped",
            exception_type=exception_type,
            exception_message=exception_message,
            stacktrace=stacktrace,
            retry_count=None,
            escalation_info=escalation_info,
            raw_line=None,
        )
    except Exception as ex:
        logger.error(f"Failed to record failed enqueue: {ex}", exc_info=True)


def _write_record(
    *,
    record_id: str,
    now: datetime,
    status: str,
    exception_type: str,
    exception_message: str,
    stacktrace: str | None,
    retry_count: int | None,
    escalation_info: EscalationInfo | None,
    raw_line: str | None,
) -> None:
    record = {
        "id": record_id,
        "recorded_at": now.isoformat(),
        "status": status,
        "exception_type": exception_type,
        "exception_message": exception_message,
        "stacktrace": stacktrace,
        "retry_count": retry_count,
        "escalation_info": escalation_info.model_dump() if escalation_info is not None else None,
        "raw_line": raw_line,
    }

    timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
    record_path = _records_dir() / f"{timestamp}-{record_id}.json"
    record_path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")

    _increment_counters(now=now, exception_type=exception_type)


def _increment_counter_file(path: Path) -> None:
    if not path.exists():
        path.touch()
        path.write_text("1")
        return

    current = path.read_text(encoding="utf-8").strip()
    value = int(current) if current else 0
    path.write_text(str(value + 1))


def _increment_counters(*, now: datetime, exception_type: str) -> None:
    pid = os.getpid()
    hour = now.strftime("%Y-%m-%d_%H")

    _increment_counter_file(_counters_dir() / "lifetime_total")
    _increment_counter_file(_counters_dir() / f"lifetime_exception_{exception_type}")
    _increment_counter_file(_counters_dir() / f"failed_{pid}_{hour}")
    _increment_counter_file(_counters_dir() / f"failed_exception_{exception_type}_{pid}_{hour}")

    last_file = _counters_dir() / "last_failed"
    last_file.touch()


def _prune_records() -> None:
    max_records = _max_records()
    max_bytes = _max_bytes()

    record_files = sorted(_records_dir().glob("*.json"), key=lambda p: p.stat().st_mtime_ns)

    while len(record_files) > max_records:
        (record_files.pop(0)).unlink(missing_ok=True)

    total_bytes = _total_stored_bytes()
    while record_files and total_bytes > max_bytes:
        to_delete = record_files.pop(0)
        try:
            total_bytes -= to_delete.stat().st_size
        except FileNotFoundError:
            pass
        to_delete.unlink(missing_ok=True)


def _total_stored_bytes() -> int:
    total = 0
    for path in _records_dir().glob("*.json"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except FileNotFoundError:
                pass
    return total


def _read_int_file(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return 0
    if not text:
        return 0
    return int(text)


def metrics_summary() -> dict:
    _ensure_dirs()

    now = datetime.now(timezone.utc)
    last_hour_str = (now - timedelta(hours=1)).strftime("%Y-%m-%d_%H")

    last_failed_time = None
    last_file = _counters_dir() / "last_failed"
    if last_file.exists():
        last_failed_time = datetime.fromtimestamp(last_file.stat().st_mtime, tz=timezone.utc).isoformat()

    last_hour_total = 0
    for f in _counters_dir().glob(f"failed_*_{last_hour_str}"):
        if f.name.startswith("failed_exception_"):
            continue
        last_hour_total += _read_int_file(f)

    last_hour_by_exception: dict[str, int] = {}
    for f in _counters_dir().glob(f"failed_exception_*_*_{last_hour_str}"):
        parts = f.name.split("_")
        # failed_exception_<exc...>_<pid>_<YYYY-MM-DD>_<HH>
        if len(parts) < 6:
            continue
        exc = "_".join(parts[2:-3])
        last_hour_by_exception[exc] = last_hour_by_exception.get(exc, 0) + _read_int_file(f)

    lifetime_total = _read_int_file(_counters_dir() / "lifetime_total")
    lifetime_by_exception: dict[str, int] = {}
    for f in _counters_dir().glob("lifetime_exception_*"):
        exc = f.name[len("lifetime_exception_") :]
        lifetime_by_exception[exc] = _read_int_file(f)

    return {
        "activity_hour": last_hour_str,
        "last_dropped_time": last_failed_time,
        "dropped_last_hour_total": last_hour_total,
        "dropped_last_hour_by_exception": last_hour_by_exception,
        "dropped_lifetime_total": lifetime_total,
        "dropped_lifetime_by_exception": lifetime_by_exception,
    }
