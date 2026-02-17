import json
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from urllib3.exceptions import MaxRetryError

from app.core.utils import generate_request_id, get_formatted_timestamp_str
from app.escalation_queue import failed_escalations
from app.escalation_queue.failed_escalations import (
    metrics_summary,
    prune_failed_escalations,
    record_failed_escalation,
)
from app.escalation_queue.manage_reader import read_from_escalation_queue
from app.escalation_queue.models import EscalationInfo, SubmitImageQueryParams
from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.queue_writer import convert_escalation_info_to_str
from app.escalation_queue.request_cache import RequestCache


@pytest.fixture(autouse=True)
def _use_tmp_dir(tmp_path: Path):
    """Redirect FAILED_ESCALATIONS_DIR to a temp directory for all tests."""
    with patch.object(failed_escalations, "FAILED_ESCALATIONS_DIR", tmp_path):
        yield


def _record(escalation_line: str | None = '{"detector_id": "det_abc"}', exc: Exception | None = None) -> None:
    record_failed_escalation(escalation_line, exc or ValueError("test error"))


def _json_files(tmp_path: Path | None = None) -> list[Path]:
    d = tmp_path or failed_escalations.FAILED_ESCALATIONS_DIR
    return sorted(d.glob("*.json"))


class TestRecordFailedEscalation:
    def test_creates_json_record(self):
        """A recorded failure should produce a JSON file with exception and escalation details."""
        _record()
        files = _json_files()
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["exception_type"] == "ValueError"
        assert "test error" in data["exception_message"]
        assert data["escalation_format"] == "json"
        assert data["escalation"]["detector_id"] == "det_abc"

    def test_records_raw_format_for_malformed_input(self):
        """Malformed (non-JSON) escalation input should be stored as raw text."""
        _record(escalation_line="not valid json {{{")
        data = json.loads(_json_files()[0].read_text())
        assert data["escalation_format"] == "raw"
        assert "not valid json" in data["escalation"]

    def test_records_none_format_for_none_input(self):
        """A None escalation line should be recorded with format 'none'."""
        _record(escalation_line=None)
        data = json.loads(_json_files()[0].read_text())
        assert data["escalation_format"] == "none"
        assert data["escalation"] is None

    def test_truncates_long_fields(self):
        """Exception messages and raw escalation payloads should be capped at their configured max length."""
        long_message = "x" * 10_000
        long_escalation = "not json " + "y" * 10_000
        _record(escalation_line=long_escalation, exc=ValueError(long_message))
        data = json.loads(_json_files()[0].read_text())
        assert len(data["exception_message"]) < len(long_message)
        assert len(data["escalation"]) < len(long_escalation)
        assert data["exception_message"].endswith("...[truncated]...\n")
        assert data["escalation"].endswith("...[truncated]...\n")

    def test_no_tmp_files_left(self):
        """Temporary files from atomic writes should be cleaned up after recording."""
        _record()
        tmp_files = list(failed_escalations.FAILED_ESCALATIONS_DIR.glob("*.json.tmp"))
        assert len(tmp_files) == 0

    def test_triggers_pruning(self):
        """Recording a failed escalation should prune old records to stay within MAX_RECORDS."""
        with patch.object(failed_escalations, "MAX_RECORDS", 2):
            for _ in range(4):
                _record()
        assert len(_json_files()) == 2

    def test_does_not_raise_on_write_failure(self):
        """Recording should swallow write errors so it never disrupts the caller."""
        with patch.object(failed_escalations, "FAILED_ESCALATIONS_DIR", Path("/nonexistent/path")):
            record_failed_escalation("line", ValueError("err"))


class TestPruneFailedEscalations:
    def test_prunes_oldest_when_over_limit(self):
        """When records exceed MAX_RECORDS, the oldest files should be removed first."""
        d = failed_escalations.FAILED_ESCALATIONS_DIR
        with patch.object(failed_escalations, "MAX_RECORDS", 3):
            for i in range(5):
                (d / f"record_{i:03d}.json").write_text("{}")
                time.sleep(0.01)  # Ensure distinct mtime
            prune_failed_escalations()
        remaining = [p.name for p in _json_files()]
        assert remaining == ["record_002.json", "record_003.json", "record_004.json"]

    def test_cleans_up_tmp_files(self):
        """Leftover .json.tmp files from interrupted writes should be removed during pruning."""
        d = failed_escalations.FAILED_ESCALATIONS_DIR
        (d / "leftover.json.tmp").write_text("{}")
        prune_failed_escalations()
        assert len(list(d.glob("*.json.tmp"))) == 0


class TestMetricsSummary:
    def _write_record(self, exc_type: str, recorded_at: datetime) -> None:
        d = failed_escalations.FAILED_ESCALATIONS_DIR
        record = {"exception_type": exc_type, "recorded_at": recorded_at.isoformat()}
        path = d / f"{recorded_at.strftime('%Y%m%d_%H%M%S_%f')}.json"
        path.write_text(json.dumps(record))

    def test_empty_directory(self):
        """An empty directory should return zero counts and no last-failed timestamp."""
        summary = metrics_summary()
        assert summary["failed_lifetime_total"] == 0
        assert summary["failed_last_hour_total"] == 0
        assert summary["last_failed_time"] is None

    def test_counts_and_breakdown(self):
        """Totals and per-exception breakdowns should reflect all recorded failures."""
        now = datetime.now(timezone.utc)
        self._write_record("ValueError", now - timedelta(minutes=10))
        self._write_record("ValueError", now - timedelta(minutes=20))
        self._write_record("FileNotFoundError", now - timedelta(minutes=30))

        summary = metrics_summary()
        assert summary["failed_lifetime_total"] == 3
        assert summary["failed_last_hour_total"] == 3
        lifetime = json.loads(summary["failed_lifetime_by_exception"])
        assert lifetime == {"FileNotFoundError": 1, "ValueError": 2}

    def test_old_records_excluded_from_last_hour(self):
        """Records older than one hour should appear in lifetime counts but not last-hour counts."""
        now = datetime.now(timezone.utc)
        self._write_record("ValueError", now - timedelta(minutes=30))
        self._write_record("TypeError", now - timedelta(hours=2))

        summary = metrics_summary()
        assert summary["failed_lifetime_total"] == 2
        assert summary["failed_last_hour_total"] == 1
        last_hour = json.loads(summary["failed_last_hour_by_exception"])
        assert last_hour == {"ValueError": 1}

    def test_exception_breakdowns_are_json_strings(self):
        """Exception breakdown fields should be serialized as JSON strings, not dicts."""
        summary = metrics_summary()
        assert isinstance(summary["failed_last_hour_by_exception"], str)
        assert isinstance(summary["failed_lifetime_by_exception"], str)


class TestFailureRecordingIntegration:
    """Tests that read_from_escalation_queue calls record_failed_escalation correctly."""

    @pytest.fixture
    def escalation_str(self) -> str:
        info = EscalationInfo(
            timestamp=get_formatted_timestamp_str(),
            detector_id="det_test",
            image_path_str="test/assets/cat.jpeg",
            request_id=generate_request_id(),
            submit_iq_params=SubmitImageQueryParams(
                patience_time=None,
                confidence_threshold=0.9,
                human_review=None,
                image_query_id="iq_test",
            ),
        )
        return convert_escalation_info_to_str(info)

    def test_records_failure_on_non_retryable_error(self, escalation_str: str):
        """When _escalate_once raises a non-retryable exception, it should be recorded as a failed escalation."""
        with tempfile.TemporaryDirectory() as tmp:
            reader = QueueReader(tmp)
            cache = RequestCache(tmp)
            err = FileNotFoundError("Image file missing.")
            with (
                patch.object(QueueReader, "__iter__", return_value=iter([escalation_str])),
                patch("app.escalation_queue.manage_reader._escalate_once", side_effect=err),
                patch("app.escalation_queue.manage_reader.record_failed_escalation") as mock_record,
            ):
                read_from_escalation_queue(reader, cache)

            mock_record.assert_called_once()
            recorded_line, recorded_exc = mock_record.call_args[0]
            assert recorded_line == escalation_str
            assert recorded_exc is err

    def test_no_failure_recorded_for_duplicate_request(self, escalation_str: str):
        """Skipping a duplicate request should not record a failed escalation."""
        with tempfile.TemporaryDirectory() as tmp:
            reader = QueueReader(tmp)
            cache = RequestCache(tmp)
            dummy_iq = Mock()
            with (
                patch.object(QueueReader, "__iter__", return_value=iter([escalation_str, escalation_str])),
                patch("app.escalation_queue.manage_reader._escalate_once", return_value=dummy_iq),
                patch("app.escalation_queue.manage_reader.record_failed_escalation") as mock_record,
            ):
                read_from_escalation_queue(reader, cache)

            mock_record.assert_not_called()

    def test_no_failure_recorded_after_retry_then_success(self, escalation_str: str):
        """A retryable error followed by success should not record a failed escalation."""
        with tempfile.TemporaryDirectory() as tmp:
            reader = QueueReader(tmp)
            cache = RequestCache(tmp)
            side_effects = [MaxRetryError(pool=None, url=None), Mock()]
            with (
                patch.object(QueueReader, "__iter__", return_value=iter([escalation_str])),
                patch("app.escalation_queue.manage_reader._escalate_once", side_effect=side_effects),
                patch("app.escalation_queue.manage_reader.time.sleep"),
                patch("app.escalation_queue.manage_reader.record_failed_escalation") as mock_record,
            ):
                read_from_escalation_queue(reader, cache)

            mock_record.assert_not_called()

    def test_records_failure_on_malformed_line(self):
        """When a queue line is malformed JSON, it should be recorded as a failed escalation."""
        with tempfile.TemporaryDirectory() as tmp:
            reader = QueueReader(tmp)
            cache = RequestCache(tmp)
            malformed = "not valid json {{{"
            with (
                patch.object(QueueReader, "__iter__", return_value=iter([malformed])),
                patch("app.escalation_queue.manage_reader.record_failed_escalation") as mock_record,
            ):
                read_from_escalation_queue(reader, cache)

            mock_record.assert_called_once()
            recorded_line, recorded_exc = mock_record.call_args[0]
            assert recorded_line == malformed
            assert isinstance(recorded_exc, (json.JSONDecodeError, TypeError))
