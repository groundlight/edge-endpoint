import contextvars
import time
from concurrent.futures import ThreadPoolExecutor

from app.profiling.context import _current_tracer, get_current_span, get_current_tracer, trace_span
from app.profiling.tracer import RequestTracer


class TestTraceSpanDecorator:
    def test_noop_when_no_tracer(self):
        """Decorated function runs normally when no tracer is in context."""
        call_count = 0

        @trace_span("test_op")
        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x + 1

        result = my_func(5)
        assert result == 6
        assert call_count == 1

    def test_creates_span_when_tracer_active(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span("child_op")
            def my_func():
                return 42

            result = my_func()
            assert result == 42

            trace = tracer.finish()
            span_names = [s.name for s in trace.spans]
            assert "child_op" in span_names
        finally:
            _current_tracer.reset(token)

    def test_span_is_finished_after_call(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span("timed_op")
            def my_func():
                time.sleep(0.01)

            my_func()

            trace = tracer.finish()
            timed_span = [s for s in trace.spans if s.name == "timed_op"][0]
            assert timed_span.end_time_ns is not None
            assert timed_span.duration_ms >= 5  # conservative for CI
        finally:
            _current_tracer.reset(token)

    def test_span_finished_on_exception(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span("failing_op")
            def my_func():
                raise ValueError("test error")

            try:
                my_func()
            except ValueError:
                pass

            trace = tracer.finish()
            failing_span = [s for s in trace.spans if s.name == "failing_op"][0]
            assert failing_span.end_time_ns is not None
        finally:
            _current_tracer.reset(token)

    def test_nested_decorators(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span("inner")
            def inner():
                return "done"

            @trace_span("outer")
            def outer():
                return inner()

            result = outer()
            assert result == "done"

            trace = tracer.finish()
            span_names = [s.name for s in trace.spans]
            assert "outer" in span_names
            assert "inner" in span_names

            inner_span = [s for s in trace.spans if s.name == "inner"][0]
            outer_span = [s for s in trace.spans if s.name == "outer"][0]
            assert inner_span.parent_span_id == outer_span.span_id
        finally:
            _current_tracer.reset(token)

    def test_current_span_set_during_execution(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        captured_span = None
        try:

            @trace_span("observable")
            def my_func():
                nonlocal captured_span
                captured_span = get_current_span()

            my_func()
            assert captured_span is not None
            assert captured_span.name == "observable"
        finally:
            _current_tracer.reset(token)

    def test_current_span_reset_after_execution(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:
            assert get_current_span() is None

            @trace_span("temp")
            def my_func():
                pass

            my_func()
            assert get_current_span() is None
        finally:
            _current_tracer.reset(token)

    def test_context_propagation_to_thread(self):
        """Verify copy_context propagates tracer to worker threads."""
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span("threaded_op")
            def worker():
                return get_current_tracer() is not None

            ctx = contextvars.copy_context()
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(ctx.run, worker)
                assert future.result() is True

            trace = tracer.finish()
            assert "threaded_op" in [s.name for s in trace.spans]
        finally:
            _current_tracer.reset(token)


class TestGetHelpers:
    def test_get_current_tracer_default_none(self):
        assert get_current_tracer() is None

    def test_get_current_span_default_none(self):
        assert get_current_span() is None
