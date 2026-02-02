import json
import logging
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path

import ksuid

from app.escalation_queue.constants import DEFAULT_QUEUE_BASE_DIR
from app.escalation_queue.models import EscalationInfo

logger = logging.getLogger(__name__)


class DroppedEscalationReason(str, Enum):
    EMPTY_LINE = "empty_line"
    CORRUPTED_NULL_BYTES = "corrupted_null_bytes"
    INVALID_JSON = "invalid_json"
    MALFORMED_ESCALATION_INFO = "malformed_escalation_info"
    QUEUE_WRITE_FAILED = "queue_write_failed"
    IMAGE_NOT_FOUND = "image_not_found"
    HTTP_400_BAD_REQUEST = "http_400_bad_request"
    HTTP_ERROR = "http_error"
    UNHANDLED_EXCEPTION = "unhandled_exception"


@lru_cache(maxsize=1)
def _base_dir() -> Path:
    default_dir = f"{DEFAULT_QUEUE_BASE_DIR}/dropped-escalations"
    return Path(os.environ.get("DROPPED_ESCALATIONS_DIR", default_dir))


def _records_dir() -> Path:
    return _base_dir() / "records"


def _counters_dir() -> Path:
    return _base_dir() / "counters"


def _ensure_dirs() -> None:
    _records_dir().mkdir(parents=True, exist_ok=True)
    _counters_dir().mkdir(parents=True, exist_ok=True)


def _increment_counter_file(path: Path) -> None:
    if not path.exists():
        path.touch()
        path.write_text("1")
        return

    current = path.read_text(encoding="utf-8").strip()
    value = int(current) if current else 0
    path.write_text(str(value + 1))


def _counter_hour(t: datetime) -> str:
    return t.strftime("%Y-%m-%d_%H")


def _max_records() -> int:
    return int(os.environ.get("DROPPED_ESCALATIONS_MAX_RECORDS", "200"))


def _max_bytes() -> int:
    return int(os.environ.get("DROPPED_ESCALATIONS_MAX_BYTES", str(500 * 1024 * 1024)))


def record_dropped_escalation(
    *,
    reason: DroppedEscalationReason,
    escalation_info: EscalationInfo | None = None,
    detector_id: str | None = None,
    submit_iq_params: dict | None = None,
    request_id: str | None = None,
    raw_line: str | None = None,
    error: str | None = None,
    retry_count: int | None = None,
) -> None:
    try:
        _ensure_dirs()

        now = datetime.now(timezone.utc)
        record_id = str(ksuid.KsuidMs())

        record = {
            "id": record_id,
            "recorded_at": now.isoformat(),
            "reason": reason.value,
            "error": error,
            "retry_count": retry_count,
            "escalation_info": escalation_info.model_dump() if escalation_info is not None else None,
            "partial_context": (
                None
                if escalation_info is not None
                else {
                    "detector_id": detector_id,
                    "submit_iq_params": submit_iq_params,
                    "request_id": request_id,
                }
            ),
            "raw_line": raw_line,
        }

        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        record_path = _records_dir() / f"{timestamp}-{record_id}.json"
        record_path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")

        counters_now = datetime.now(timezone.utc)
        hour = _counter_hour(counters_now)
        pid = os.getpid()

        _increment_counter_file(_counters_dir() / "lifetime_total")
        _increment_counter_file(_counters_dir() / f"lifetime_reason_{reason.value}")
        _increment_counter_file(_counters_dir() / f"dropped_{pid}_{hour}")
        _increment_counter_file(_counters_dir() / f"dropped_reason_{reason.value}_{pid}_{hour}")

        last_file = _counters_dir() / "last_dropped"
        last_file.touch()

        _prune_records()
    except Exception as ex:
        logger.error(f"Failed to record dropped escalation: {ex}", exc_info=True)


def _prune_records() -> None:
    max_records = _max_records()
    max_bytes = _max_bytes()

    record_files = sorted(_records_dir().glob("*.json"), key=lambda p: p.stat().st_mtime_ns)

    while len(record_files) > max_records:
        _delete_record_file(record_files.pop(0))

    total_bytes = _total_stored_bytes()
    while record_files and total_bytes > max_bytes:
        to_delete = record_files.pop(0)
        total_bytes -= to_delete.stat().st_size if to_delete.exists() else 0
        _delete_record_file(to_delete)


def _delete_record_file(record_path: Path) -> None:
    try:
        record_path.unlink(missing_ok=True)
    except Exception:
        pass


def _total_stored_bytes() -> int:
    total = 0
    for path in _records_dir().glob("*"):
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
    last_hour = _counter_hour(now - timedelta(hours=1))

    last_dropped_time = None
    last_file = _counters_dir() / "last_dropped"
    if last_file.exists():
        last_dropped_time = datetime.fromtimestamp(last_file.stat().st_mtime, tz=timezone.utc).isoformat()

    last_hour_total = 0
    for f in _counters_dir().glob(f"dropped_*_{last_hour}"):
        last_hour_total += _read_int_file(f)

    last_hour_by_reason: dict[str, int] = {}
    for reason in DroppedEscalationReason:
        total = 0
        for f in _counters_dir().glob(f"dropped_reason_{reason.value}_*_{last_hour}"):
            total += _read_int_file(f)
        last_hour_by_reason[reason.value] = total

    lifetime_total = _read_int_file(_counters_dir() / "lifetime_total")
    lifetime_by_reason = {
        reason.value: _read_int_file(_counters_dir() / f"lifetime_reason_{reason.value}")
        for reason in DroppedEscalationReason
    }

    return {
        "activity_hour": last_hour,
        "last_dropped_time": last_dropped_time,
        "dropped_last_hour_total": last_hour_total,
        "dropped_last_hour_by_reason": last_hour_by_reason,
        "dropped_lifetime_total": lifetime_total,
        "dropped_lifetime_by_reason": lifetime_by_reason,
        "stored_records": len(list(_records_dir().glob("*.json"))),
        "stored_bytes": _total_stored_bytes(),
        "max_records": _max_records(),
        "max_bytes": _max_bytes(),
        "base_dir": str(_base_dir()),
    }
