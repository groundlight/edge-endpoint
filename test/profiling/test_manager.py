import json
import os
import time

import pytest

from app.profiling.manager import ProfilingManager
from app.profiling.models import Span, Trace


@pytest.fixture
def tmp_profiling_dir(tmp_path):
    return str(tmp_path / "profiling")


@pytest.fixture
def manager(tmp_profiling_dir):
    return ProfilingManager(base_dir=tmp_profiling_dir)


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
    def test_writes_jsonl_file(self, manager, tmp_profiling_dir):
        trace = _make_trace()
        manager.record_trace(trace)

        traces_dir = os.path.join(tmp_profiling_dir, "traces")
        files = list(os.listdir(traces_dir))
        assert len(files) == 1
        assert files[0].endswith(".jsonl")

        with open(os.path.join(traces_dir, files[0])) as f:
            lines = f.readlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["trace_id"] == "t1"
        assert len(parsed["spans"]) == 2

    def test_multiple_traces_same_file(self, manager, tmp_profiling_dir):
        manager.record_trace(_make_trace(trace_id="t1"))
        manager.record_trace(_make_trace(trace_id="t2"))

        traces_dir = os.path.join(tmp_profiling_dir, "traces")
        files = list(os.listdir(traces_dir))
        assert len(files) == 1

        with open(os.path.join(traces_dir, files[0])) as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_creates_traces_directory(self, tmp_profiling_dir):
        manager = ProfilingManager(base_dir=tmp_profiling_dir)
        assert os.path.isdir(os.path.join(tmp_profiling_dir, "traces"))


class TestFileRotation:
    def test_rotation_after_interval(self, tmp_profiling_dir):
        manager = ProfilingManager(base_dir=tmp_profiling_dir)
        manager.record_trace(_make_trace(trace_id="t1"))

        # Force rotation by backdating the creation time
        manager._current_file_created_at = time.monotonic() - 400  # >300s

        manager.record_trace(_make_trace(trace_id="t2"))

        traces_dir = os.path.join(tmp_profiling_dir, "traces")
        files = list(os.listdir(traces_dir))
        assert len(files) == 2


class TestCleanup:
    def test_cleanup_old_files(self, manager, tmp_profiling_dir):
        traces_dir = os.path.join(tmp_profiling_dir, "traces")
        # Create a fake old file
        old_file = os.path.join(traces_dir, "traces_123_2025-01-01_00-00-00.jsonl")
        with open(old_file, "w") as f:
            f.write("{}\n")
        # Set mtime to 48 hours ago
        old_time = time.time() - 48 * 3600
        os.utime(old_file, (old_time, old_time))

        # Create a recent file
        manager.record_trace(_make_trace())

        deleted = manager.cleanup_old_files()
        assert deleted == 1
        remaining = list(os.listdir(traces_dir))
        assert len(remaining) == 1
        assert "2025-01-01" not in remaining[0]

    def test_cleanup_no_old_files(self, manager):
        manager.record_trace(_make_trace())
        deleted = manager.cleanup_old_files()
        assert deleted == 0


class TestComputeAggregation:
    def test_basic_aggregation(self, manager):
        for i in range(10):
            trace = _make_trace(
                trace_id=f"t{i}",
                spans=[
                    Span(
                        name="primary_inference",
                        trace_id=f"t{i}",
                        span_id=f"s{i}",
                        parent_span_id=None,
                        start_time_ns=0,
                        end_time_ns=(i + 1) * 10_000_000,  # 10ms, 20ms, ..., 100ms
                    ),
                ],
            )
            manager.record_trace(trace)

        agg = manager.compute_aggregation(hours=1)
        assert "primary_inference" in agg
        stats = agg["primary_inference"]
        assert stats["count"] == 10
        assert stats["min_ms"] == 10.0
        assert stats["max_ms"] == 100.0
        assert stats["mean_ms"] == 55.0
        assert stats["p50_ms"] == 60.0  # sorted: 10,20,...,100 -> index 5 = 60

    def test_filter_by_detector(self, manager):
        manager.record_trace(_make_trace(trace_id="t1", detector_id="det_a"))
        manager.record_trace(_make_trace(trace_id="t2", detector_id="det_b"))

        agg_a = manager.compute_aggregation(detector_id="det_a", hours=1)
        agg_b = manager.compute_aggregation(detector_id="det_b", hours=1)

        assert agg_a["root"]["count"] == 1
        assert agg_b["root"]["count"] == 1

    def test_empty_aggregation(self, manager):
        agg = manager.compute_aggregation(hours=1)
        assert agg == {}

    def test_skips_unfinished_spans(self, manager):
        trace = _make_trace(
            spans=[
                Span(
                    name="unfinished",
                    trace_id="t1",
                    span_id="s1",
                    parent_span_id=None,
                    start_time_ns=0,
                    # end_time_ns not set -> duration_ms = -1
                ),
            ],
        )
        manager.record_trace(trace)
        agg = manager.compute_aggregation(hours=1)
        assert agg == {}

    def test_stddev_calculation(self, manager):
        # All same duration -> stddev should be 0
        for i in range(5):
            trace = _make_trace(
                trace_id=f"t{i}",
                spans=[
                    Span(
                        name="constant",
                        trace_id=f"t{i}",
                        span_id=f"s{i}",
                        parent_span_id=None,
                        start_time_ns=0,
                        end_time_ns=50_000_000,  # always 50ms
                    ),
                ],
            )
            manager.record_trace(trace)

        agg = manager.compute_aggregation(hours=1)
        assert agg["constant"]["stddev_ms"] == 0.0
