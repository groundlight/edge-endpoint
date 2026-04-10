import json
import os
import time

import pytest

from app.profiling.manager import ProfilingManager
from app.profiling.models import Span, Trace


@pytest.fixture
def tmp_traces_dir(tmp_path):
    return str(tmp_path / "edge-profiling")


@pytest.fixture
def manager(tmp_traces_dir):
    return ProfilingManager(traces_dir=tmp_traces_dir)


def _make_trace(trace_id="t1", detector_id="det_1", spans=None):
    if spans is None:
        spans = [
            Span(
                name="root",
                trace_id=trace_id,
                span_id="s1",
                parent_span_id=None,
                start_time_ns=0,
                end_time_ns=100_000_000,  # 100ms
            ),
            Span(
                name="primary_inference",
                trace_id=trace_id,
                span_id="s2",
                parent_span_id="s1",
                start_time_ns=10_000_000,
                end_time_ns=90_000_000,  # 80ms
            ),
        ]
    return Trace(
        trace_id=trace_id,
        detector_id=detector_id,
        start_wall_time_iso="2026-04-01T00:00:00+00:00",
        spans=spans,
    )


class TestRecordTrace:
    def test_writes_jsonl_file(self, manager, tmp_traces_dir):
        trace = _make_trace()
        manager.record_trace(trace)

        files = list(os.listdir(tmp_traces_dir))
        assert len(files) == 1
        assert files[0].endswith(".jsonl")

        with open(os.path.join(tmp_traces_dir, files[0])) as f:
            lines = f.readlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["trace_id"] == "t1"
        assert len(parsed["spans"]) == 2

    def test_multiple_traces_same_file(self, manager, tmp_traces_dir):
        manager.record_trace(_make_trace(trace_id="t1"))
        manager.record_trace(_make_trace(trace_id="t2"))

        files = list(os.listdir(tmp_traces_dir))
        assert len(files) == 1

        with open(os.path.join(tmp_traces_dir, files[0])) as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_creates_traces_directory(self, tmp_traces_dir):
        ProfilingManager(traces_dir=tmp_traces_dir)
        assert os.path.isdir(tmp_traces_dir)


class TestFileRotation:
    def test_rotation_after_interval(self, tmp_traces_dir):
        manager = ProfilingManager(traces_dir=tmp_traces_dir)
        manager.record_trace(_make_trace(trace_id="t1"))

        # Force rotation by backdating the creation time
        manager._current_file_created_at = time.monotonic() - 400  # >300s

        manager.record_trace(_make_trace(trace_id="t2"))

        files = list(os.listdir(tmp_traces_dir))
        assert len(files) == 2


class TestCleanup:
    def test_cleanup_old_files(self, manager, tmp_traces_dir):
        # Create a fake old file
        old_file = os.path.join(tmp_traces_dir, "traces_123_2025-01-01_00-00-00.jsonl")
        with open(old_file, "w") as f:
            f.write("{}\n")
        # Set mtime to 48 hours ago
        old_time = time.time() - 48 * 3600
        os.utime(old_file, (old_time, old_time))

        # Create a recent file
        manager.record_trace(_make_trace())

        deleted = manager.cleanup_old_files()
        assert deleted == 1
        remaining = list(os.listdir(tmp_traces_dir))
        assert len(remaining) == 1
        assert "2025-01-01" not in remaining[0]

    def test_cleanup_no_old_files(self, manager):
        manager.record_trace(_make_trace())
        deleted = manager.cleanup_old_files()
        assert deleted == 0
