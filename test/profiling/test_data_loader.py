import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.profiling.data_loader import (
    compute_span_stats,
    compute_time_series,
    get_detector_ids,
    get_trace_detail,
    load_traces,
)


def _make_trace_dict(
    trace_id="t1",
    detector_id="det_1",
    start_wall_time_iso=None,
    spans=None,
):
    if start_wall_time_iso is None:
        start_wall_time_iso = datetime.now(timezone.utc).isoformat()
    if spans is None:
        spans = [
            {
                "name": "request",
                "trace_id": trace_id,
                "span_id": "s1",
                "parent_span_id": None,
                "start_time_ns": 0,
                "end_time_ns": 100_000_000,
                "duration_ms": 100.0,
                "annotations": {},
            },
            {
                "name": "primary_inference",
                "trace_id": trace_id,
                "span_id": "s2",
                "parent_span_id": "s1",
                "start_time_ns": 10_000_000,
                "end_time_ns": 90_000_000,
                "duration_ms": 80.0,
                "annotations": {},
            },
        ]
    return {
        "trace_id": trace_id,
        "detector_id": detector_id,
        "start_wall_time_iso": start_wall_time_iso,
        "spans": spans,
    }


def _write_traces(traces_dir, traces, filename="traces_1_2026-04-01_00-00-00_000000.jsonl"):
    os.makedirs(traces_dir, exist_ok=True)
    filepath = os.path.join(traces_dir, filename)
    with open(filepath, "a") as f:
        for trace in traces:
            f.write(json.dumps(trace) + "\n")
    return filepath


class TestLoadTraces:
    def test_loads_traces_from_dir(self, tmp_path):
        traces_dir = str(tmp_path / "profiling")
        _write_traces(traces_dir, [_make_trace_dict(trace_id="t1"), _make_trace_dict(trace_id="t2")])

        result = load_traces(traces_dir)
        assert len(result) == 2
        assert result[0]["trace_id"] == "t1"
        assert result[1]["trace_id"] == "t2"

    def test_empty_directory(self, tmp_path):
        traces_dir = str(tmp_path / "profiling")
        os.makedirs(traces_dir)
        assert load_traces(traces_dir) == []

    def test_nonexistent_directory(self, tmp_path):
        assert load_traces(str(tmp_path / "nonexistent")) == []

    def test_filter_by_detector_id(self, tmp_path):
        traces_dir = str(tmp_path / "profiling")
        _write_traces(traces_dir, [
            _make_trace_dict(trace_id="t1", detector_id="det_a"),
            _make_trace_dict(trace_id="t2", detector_id="det_b"),
            _make_trace_dict(trace_id="t3", detector_id="det_a"),
        ])

        result = load_traces(traces_dir, detector_id="det_a")
        assert len(result) == 2
        assert all(t["detector_id"] == "det_a" for t in result)

    def test_filter_by_time(self, tmp_path):
        traces_dir = str(tmp_path / "profiling")
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=2)).isoformat()
        recent_time = (now - timedelta(minutes=5)).isoformat()

        _write_traces(traces_dir, [
            _make_trace_dict(trace_id="old", start_wall_time_iso=old_time),
            _make_trace_dict(trace_id="recent", start_wall_time_iso=recent_time),
        ])

        result = load_traces(traces_dir, since_minutes=30)
        assert len(result) == 1
        assert result[0]["trace_id"] == "recent"

    def test_filter_by_time_and_detector(self, tmp_path):
        """Both filters applied together should intersect."""
        traces_dir = str(tmp_path / "profiling")
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=2)).isoformat()
        recent = (now - timedelta(minutes=5)).isoformat()

        _write_traces(traces_dir, [
            _make_trace_dict(trace_id="old_a", detector_id="det_a", start_wall_time_iso=old),
            _make_trace_dict(trace_id="recent_a", detector_id="det_a", start_wall_time_iso=recent),
            _make_trace_dict(trace_id="recent_b", detector_id="det_b", start_wall_time_iso=recent),
        ])

        result = load_traces(traces_dir, since_minutes=30, detector_id="det_a")
        assert len(result) == 1
        assert result[0]["trace_id"] == "recent_a"

    def test_skips_malformed_json(self, tmp_path):
        traces_dir = str(tmp_path / "profiling")
        os.makedirs(traces_dir)
        filepath = os.path.join(traces_dir, "traces_1_2026-04-01_00-00-00_000000.jsonl")
        with open(filepath, "w") as f:
            f.write(json.dumps(_make_trace_dict(trace_id="good")) + "\n")
            f.write("this is not json\n")
            f.write(json.dumps(_make_trace_dict(trace_id="also_good")) + "\n")

        result = load_traces(traces_dir)
        assert len(result) == 2
        assert result[0]["trace_id"] == "good"
        assert result[1]["trace_id"] == "also_good"

    def test_skips_empty_lines(self, tmp_path):
        traces_dir = str(tmp_path / "profiling")
        os.makedirs(traces_dir)
        filepath = os.path.join(traces_dir, "traces_1_2026-04-01_00-00-00_000000.jsonl")
        with open(filepath, "w") as f:
            f.write(json.dumps(_make_trace_dict()) + "\n")
            f.write("\n")
            f.write("  \n")

        result = load_traces(traces_dir)
        assert len(result) == 1

    def test_reads_multiple_files(self, tmp_path):
        traces_dir = str(tmp_path / "profiling")
        _write_traces(traces_dir, [_make_trace_dict(trace_id="t1")], filename="traces_1_2026-04-01_00-00-00_000000.jsonl")
        _write_traces(traces_dir, [_make_trace_dict(trace_id="t2")], filename="traces_1_2026-04-01_00-05-00_000000.jsonl")

        result = load_traces(traces_dir)
        assert len(result) == 2

    def test_skips_old_files_by_mtime(self, tmp_path):
        traces_dir = str(tmp_path / "profiling")
        now = datetime.now(timezone.utc)

        old_path = _write_traces(
            traces_dir,
            [_make_trace_dict(trace_id="old", start_wall_time_iso=(now - timedelta(hours=3)).isoformat())],
            filename="traces_1_old.jsonl",
        )
        _write_traces(
            traces_dir,
            [_make_trace_dict(trace_id="recent", start_wall_time_iso=now.isoformat())],
            filename="traces_1_recent.jsonl",
        )

        import time as time_mod

        old_mtime = time_mod.time() - 7200
        os.utime(old_path, (old_mtime, old_mtime))

        result = load_traces(traces_dir, since_minutes=60)
        assert len(result) == 1
        assert result[0]["trace_id"] == "recent"

    def test_skips_naive_timestamps_when_filtering_by_time(self, tmp_path):
        """A timezone-naive timestamp would cause TypeError in aware comparison. Skip instead."""
        traces_dir = str(tmp_path / "profiling")
        now = datetime.now(timezone.utc)
        _write_traces(traces_dir, [
            _make_trace_dict(trace_id="naive", start_wall_time_iso="2026-04-01T12:00:00"),
            _make_trace_dict(trace_id="aware", start_wall_time_iso=now.isoformat()),
        ])

        # Should not raise, and should skip the naive trace.
        result = load_traces(traces_dir, since_minutes=60)
        assert len(result) == 1
        assert result[0]["trace_id"] == "aware"

    def test_naive_timestamps_kept_when_no_time_filter(self, tmp_path):
        """Without a time filter, naive timestamps are kept (no comparison needed)."""
        traces_dir = str(tmp_path / "profiling")
        _write_traces(traces_dir, [
            _make_trace_dict(trace_id="naive", start_wall_time_iso="2026-04-01T12:00:00"),
        ])

        result = load_traces(traces_dir)
        assert len(result) == 1


class TestComputeSpanStats:
    def test_basic_stats(self):
        traces = [
            _make_trace_dict(
                trace_id=f"t{i}",
                spans=[{
                    "name": "request",
                    "trace_id": f"t{i}",
                    "span_id": "s1",
                    "parent_span_id": None,
                    "start_time_ns": 0,
                    "end_time_ns": (i + 1) * 10_000_000,
                    "duration_ms": (i + 1) * 10.0,
                    "annotations": {},
                }],
            )
            for i in range(10)
        ]

        stats = compute_span_stats(traces)
        assert "request" in stats
        assert stats["request"]["count"] == 10
        assert stats["request"]["min"] == 10.0
        assert stats["request"]["max"] == 100.0
        assert stats["request"]["mean"] == 55.0

    def test_percentiles_inclusive_method_clamps_to_range(self):
        """p99 must not exceed observed max — this is the method='inclusive' guarantee."""
        # Values 10, 20, ..., 100 — max is 100
        traces = [
            _make_trace_dict(
                trace_id=f"t{i}",
                spans=[{
                    "name": "request",
                    "trace_id": f"t{i}",
                    "span_id": "s1",
                    "parent_span_id": None,
                    "start_time_ns": 0,
                    "end_time_ns": (i + 1) * 10_000_000,
                    "duration_ms": (i + 1) * 10.0,
                    "annotations": {},
                }],
            )
            for i in range(10)
        ]

        stats = compute_span_stats(traces)["request"]
        # p99 <= max (would fail with method='exclusive')
        assert stats["p99"] <= stats["max"]
        assert stats["p95"] <= stats["max"]
        assert stats["p50"] >= stats["min"]

    def test_percentile_values_ten_samples(self):
        """Pin expected percentile values so method changes don't silently regress."""
        durations = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        traces = [
            _make_trace_dict(
                trace_id=f"t{i}",
                spans=[{
                    "name": "request",
                    "trace_id": f"t{i}",
                    "span_id": "s1",
                    "parent_span_id": None,
                    "start_time_ns": 0,
                    "end_time_ns": int(d * 1_000_000),
                    "duration_ms": float(d),
                    "annotations": {},
                }],
            )
            for i, d in enumerate(durations)
        ]
        stats = compute_span_stats(traces)["request"]
        # With inclusive method and 10 samples, p50 interpolates between 5th and 6th (50 and 60) -> 55
        assert stats["p50"] == 55.0
        # p95 is the 95th percentile with inclusive — interpolates between 90 and 100
        assert 90.0 <= stats["p95"] <= 100.0

    def test_multiple_span_types(self):
        traces = [_make_trace_dict()]  # has "request" and "primary_inference" spans
        stats = compute_span_stats(traces)
        assert "request" in stats
        assert "primary_inference" in stats

    def test_skips_negative_durations(self):
        traces = [_make_trace_dict(spans=[{
            "name": "unfinished",
            "trace_id": "t1",
            "span_id": "s1",
            "parent_span_id": None,
            "start_time_ns": 0,
            "end_time_ns": None,
            "duration_ms": -1.0,
            "annotations": {},
        }])]
        stats = compute_span_stats(traces)
        assert stats == {}

    def test_empty_traces(self):
        assert compute_span_stats([]) == {}

    def test_single_trace_percentiles(self):
        traces = [_make_trace_dict()]
        stats = compute_span_stats(traces)
        # With a single data point, p50/p95/p99 should all equal that point
        assert stats["request"]["p50"] == 100.0
        assert stats["request"]["p95"] == 100.0
        assert stats["request"]["p99"] == 100.0


class TestComputeTimeSeries:
    def test_buckets_traces(self):
        base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        traces = [
            _make_trace_dict(trace_id=f"t{i}", start_wall_time_iso=(base + timedelta(minutes=i)).isoformat())
            for i in range(10)
        ]

        series = compute_time_series(traces, "request", bucket_minutes=5)
        assert len(series) == 2
        assert all("p50" in entry and "p95" in entry and "count" in entry for entry in series)
        assert series[0]["count"] == 5
        assert series[1]["count"] == 5

    def test_bucket_stats_pinned(self):
        """Verify percentile computation for a known bucket."""
        base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        # All 5 traces fall in the 12:00-12:04 bucket; durations 10..50
        traces = []
        for i, dur in enumerate([10, 20, 30, 40, 50]):
            traces.append(_make_trace_dict(
                trace_id=f"t{i}",
                start_wall_time_iso=(base + timedelta(minutes=i)).isoformat(),
                spans=[{
                    "name": "request", "trace_id": f"t{i}", "span_id": "s1",
                    "parent_span_id": None, "start_time_ns": 0,
                    "end_time_ns": dur * 1_000_000, "duration_ms": float(dur),
                    "annotations": {},
                }],
            ))

        series = compute_time_series(traces, "request", bucket_minutes=5)
        assert len(series) == 1
        b = series[0]
        assert b["count"] == 5
        assert b["mean"] == 30.0
        # p50 with inclusive method on [10,20,30,40,50] -> 30
        assert b["p50"] == 30.0
        # p95 clamped within range
        assert b["p95"] <= 50.0

    def test_nonexistent_span(self):
        traces = [_make_trace_dict()]
        series = compute_time_series(traces, "nonexistent_span")
        assert series == []

    def test_empty_traces(self):
        assert compute_time_series([], "request") == []

    def test_rejects_zero_bucket_minutes(self):
        with pytest.raises(ValueError):
            compute_time_series([], "request", bucket_minutes=0)

    def test_rejects_negative_bucket_minutes(self):
        with pytest.raises(ValueError):
            compute_time_series([], "request", bucket_minutes=-5)

    def test_rejects_non_divisor_bucket_minutes(self):
        """bucket_minutes must divide 60 evenly (avoids drift across hours)."""
        with pytest.raises(ValueError):
            compute_time_series([], "request", bucket_minutes=7)


class TestGetDetectorIds:
    def test_extracts_unique_ids(self):
        traces = [
            _make_trace_dict(detector_id="det_a"),
            _make_trace_dict(detector_id="det_b"),
            _make_trace_dict(detector_id="det_a"),
        ]
        ids = get_detector_ids(traces)
        assert ids == ["det_a", "det_b"]

    def test_excludes_unknown(self):
        traces = [
            _make_trace_dict(detector_id="det_a"),
            _make_trace_dict(detector_id="unknown"),
        ]
        ids = get_detector_ids(traces)
        assert ids == ["det_a"]

    def test_empty_traces(self):
        assert get_detector_ids([]) == []


class TestGetTraceDetail:
    def test_finds_trace(self):
        traces = [
            _make_trace_dict(trace_id="t1"),
            _make_trace_dict(trace_id="t2"),
        ]
        result = get_trace_detail(traces, "t2")
        assert result is not None
        assert result["trace_id"] == "t2"

    def test_sorts_spans_by_start_time(self):
        traces = [_make_trace_dict(
            trace_id="t1",
            spans=[
                {"name": "b", "trace_id": "t1", "span_id": "s2", "parent_span_id": "s1",
                 "start_time_ns": 50, "end_time_ns": 100, "duration_ms": 0.00005, "annotations": {}},
                {"name": "a", "trace_id": "t1", "span_id": "s1", "parent_span_id": None,
                 "start_time_ns": 0, "end_time_ns": 100, "duration_ms": 0.0001, "annotations": {}},
            ],
        )]
        result = get_trace_detail(traces, "t1")
        assert result["spans"][0]["name"] == "a"
        assert result["spans"][1]["name"] == "b"

    def test_returns_none_for_missing(self):
        traces = [_make_trace_dict(trace_id="t1")]
        assert get_trace_detail(traces, "nonexistent") is None

    def test_empty_traces(self):
        assert get_trace_detail([], "t1") is None


class TestDashboardSmoke:
    """Smoke tests for the Marimo dashboard. Skipped when the `profiling` dependency
    group is not installed (marimo/plotly missing). Install with `poetry install --with profiling`.
    """

    def test_dashboard_module_imports(self):
        """Catch syntax errors in dashboard.py without executing the marimo cell graph.

        Note: @app.cell bodies are NOT executed by import. This verifies top-level
        syntax plus the @app.function bodies that are evaluated at import time.
        """
        import importlib.util

        marimo = pytest.importorskip("marimo")

        spec = importlib.util.find_spec("app.profiling.dashboard")
        assert spec is not None, "dashboard module not discoverable"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert isinstance(module.app, marimo.App), "module.app should be a marimo.App instance"
        assert callable(module.span_sort_key), "span_sort_key should be a callable @app.function"
        assert callable(module.build_waterfall), "build_waterfall should be a callable @app.function"

    def test_span_sort_key(self):
        """Verify the 'request'-first ordering helper used across cells."""
        pytest.importorskip("marimo")
        from app.profiling.dashboard import span_sort_key

        names = ["get_inference_result", "request", "primary_inference"]
        assert sorted(names, key=span_sort_key) == ["request", "get_inference_result", "primary_inference"]

    def test_build_waterfall_renders(self):
        """Exercise the waterfall helper end-to-end with synthetic data.

        This verifies that plotly is installed, that the function handles the
        Gantt-style rendering without crashing, and that defensive .get() access
        works for missing/null fields.
        """
        mo = pytest.importorskip("marimo")
        go = pytest.importorskip("plotly.graph_objects")

        from app.profiling.dashboard import build_waterfall

        detail = {"trace_id": "t" * 32, "detector_id": "det_a"}
        spans = [
            {"name": "request", "span_id": "s0", "parent_span_id": None,
             "start_time_ns": 0, "end_time_ns": 100_000_000, "duration_ms": 100.0, "annotations": {}},
            {"name": "primary_inference", "span_id": "s1", "parent_span_id": "s0",
             "start_time_ns": 10_000_000, "end_time_ns": 90_000_000, "duration_ms": 80.0,
             "annotations": {"http.status_code": "200"}},
            # Unfinished span — should be skipped in the chart but present in the table.
            {"name": "aborted", "span_id": "s2", "parent_span_id": "s0",
             "start_time_ns": 50_000_000, "end_time_ns": None, "duration_ms": -1.0, "annotations": None},
        ]

        colors = {"request": "#636EFA", "primary_inference": "#AB63FA"}
        result = build_waterfall(detail, spans, go, mo, colors, "#B6B6B6")
        # Should produce a marimo Html-like object (from mo.vstack) with a renderable repr.
        assert result is not None
        assert hasattr(result, "_mime_"), "build_waterfall should return a marimo renderable"
