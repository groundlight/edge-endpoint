import json

from app.profiling.models import Span, Trace


class TestSpan:
    def test_duration_ms(self):
        span = Span(
            name="test",
            trace_id="abc",
            span_id="def",
            parent_span_id=None,
            start_time_ns=1_000_000_000,
            end_time_ns=1_100_000_000,
        )
        assert span.duration_ms == 100.0

    def test_duration_ms_unfinished(self):
        span = Span(
            name="test",
            trace_id="abc",
            span_id="def",
            parent_span_id=None,
            start_time_ns=1_000_000_000,
        )
        assert span.duration_ms == -1.0

    def test_to_dict(self):
        span = Span(
            name="primary_inference",
            trace_id="aaa",
            span_id="bbb",
            parent_span_id="ccc",
            start_time_ns=100,
            end_time_ns=200,
            annotations={"key": "value"},
        )
        d = span.to_dict()
        assert d["name"] == "primary_inference"
        assert d["trace_id"] == "aaa"
        assert d["span_id"] == "bbb"
        assert d["parent_span_id"] == "ccc"
        assert d["start_time_ns"] == 100
        assert d["end_time_ns"] == 200
        assert d["duration_ms"] == 0.0001
        assert d["annotations"] == {"key": "value"}
        # Verify JSON round-trip
        parsed = json.loads(json.dumps(d))
        assert parsed["name"] == "primary_inference"
        assert parsed["parent_span_id"] == "ccc"

    def test_annotations_default_empty(self):
        span = Span(name="x", trace_id="a", span_id="b", parent_span_id=None, start_time_ns=0)
        assert span.annotations == {}


class TestTrace:
    def test_to_dict(self):
        span = Span(
            name="root",
            trace_id="t1",
            span_id="s1",
            parent_span_id=None,
            start_time_ns=0,
            end_time_ns=100,
        )
        trace = Trace(
            trace_id="t1",
            detector_id="det_123",
            start_wall_time_iso="2026-04-01T00:00:00+00:00",
            spans=[span],
        )
        d = trace.to_dict()
        assert d["trace_id"] == "t1"
        assert d["detector_id"] == "det_123"
        assert d["start_wall_time_iso"] == "2026-04-01T00:00:00+00:00"
        assert len(d["spans"]) == 1
        assert d["spans"][0]["name"] == "root"
        # Verify JSON round-trip
        parsed = json.loads(json.dumps(d))
        assert parsed["trace_id"] == "t1"
        assert len(parsed["spans"]) == 1

    def test_empty_spans(self):
        trace = Trace(trace_id="t", detector_id="det_1", start_wall_time_iso="2026-01-01T00:00:00+00:00")
        assert trace.spans == []
        assert trace.to_dict()["spans"] == []
