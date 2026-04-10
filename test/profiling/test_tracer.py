import time
from concurrent.futures import ThreadPoolExecutor

from app.profiling.tracer import RequestTracer


class TestRequestTracer:
    def test_creates_root_span(self):
        tracer = RequestTracer(operation="test_op", detector_id="det_abc")
        assert len(tracer.trace_id) == 32
        assert len(tracer.root_span_id) == 16

        trace = tracer.finish()
        assert trace.detector_id == "det_abc"
        assert trace.trace_id == tracer.trace_id
        assert len(trace.spans) == 1
        assert trace.spans[0].name == "test_op"
        assert trace.spans[0].parent_span_id is None
        assert trace.spans[0].end_time_ns is not None
        assert "T" in trace.start_wall_time_iso

    def test_start_and_end_span(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        child = tracer.start_span("child_op")
        assert child.parent_span_id == tracer.root_span_id
        assert child.end_time_ns is None

        tracer.end_span(child, key1="val1")
        assert child.end_time_ns is not None
        assert child.annotations == {"key1": "val1"}

        trace = tracer.finish()
        assert len(trace.spans) == 2

    def test_nested_spans(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        child = tracer.start_span("child")
        grandchild = tracer.start_span("grandchild", parent_span_id=child.span_id)
        assert grandchild.parent_span_id == child.span_id

        tracer.end_span(grandchild)
        tracer.end_span(child)
        trace = tracer.finish()
        assert len(trace.spans) == 3

    def test_annotate(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        span = tracer.start_span("span1")
        tracer.annotate(span, foo="bar", baz="qux")
        assert span.annotations == {"foo": "bar", "baz": "qux"}

    def test_span_timing(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        span = tracer.start_span("timed")
        time.sleep(0.01)  # 10ms
        tracer.end_span(span)
        assert span.duration_ms >= 5  # at least 5ms (conservative for CI)

    def test_thread_safety_concurrent_spans(self):
        """Create and end spans from multiple threads concurrently."""
        tracer = RequestTracer(operation="root", detector_id="det_1")
        num_threads = 10

        def create_and_end_span(i):
            span = tracer.start_span(f"thread_{i}")
            time.sleep(0.001)
            tracer.end_span(span, thread=str(i))
            return span

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(create_and_end_span, i) for i in range(num_threads)]
            spans = [f.result() for f in futures]

        trace = tracer.finish()
        # root + num_threads child spans
        assert len(trace.spans) == num_threads + 1
        # All child spans should be finished
        for span in spans:
            assert span.end_time_ns is not None
