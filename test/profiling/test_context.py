import asyncio
import contextvars
import time
from concurrent.futures import ThreadPoolExecutor

from app.profiling.context import _current_tracer, get_current_span, get_current_tracer, trace_span
from app.profiling.tracer import RequestTracer


class TestTraceSpanDecorator:
    def test_noop_when_no_tracer(self):
        """Decorated function runs normally when no tracer is in context."""
        call_count = 0

        @trace_span
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

            @trace_span
            def my_func():
                time.sleep(0.01)
                return 42

            result = my_func()
            assert result == 42

            trace = tracer.finish()
            span = [s for s in trace.spans if s.name == "my_func"][0]
            assert span.end_time_ns is not None
            assert span.duration_ms >= 5  # conservative for CI
        finally:
            _current_tracer.reset(token)

    def test_span_finished_on_exception(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span
            def failing_func():
                raise ValueError("test error")

            try:
                failing_func()
            except ValueError:
                pass

            trace = tracer.finish()
            failing_span = [s for s in trace.spans if s.name == "failing_func"][0]
            assert failing_span.end_time_ns is not None
        finally:
            _current_tracer.reset(token)

    def test_nested_decorators(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span
            def inner():
                return "done"

            @trace_span
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

    def test_current_span_scoped_to_execution(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        captured_span = None
        try:
            assert get_current_span() is None

            @trace_span
            def observable():
                nonlocal captured_span
                captured_span = get_current_span()

            observable()
            assert captured_span is not None
            assert captured_span.name == "observable"
            assert get_current_span() is None  # reset after execution
        finally:
            _current_tracer.reset(token)

    def test_context_propagation_to_thread(self):
        """Verify copy_context propagates tracer to worker threads."""
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span
            def worker():
                return get_current_tracer() is not None

            ctx = contextvars.copy_context()
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(ctx.run, worker)
                assert future.result() is True

            trace = tracer.finish()
            assert "worker" in [s.name for s in trace.spans]
        finally:
            _current_tracer.reset(token)


class TestTraceSpanDecoratorAsync:
    def test_noop_when_no_tracer(self):
        """Async decorated function runs normally when no tracer is in context."""
        call_count = 0

        @trace_span
        async def my_func(x):
            nonlocal call_count
            call_count += 1
            return x + 1

        result = asyncio.run(my_func(5))
        assert result == 6
        assert call_count == 1

    def test_creates_span_when_tracer_active(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span
            async def my_func():
                await asyncio.sleep(0.01)
                return 42

            result = asyncio.run(my_func())
            assert result == 42

            trace = tracer.finish()
            span = [s for s in trace.spans if s.name == "my_func"][0]
            assert span.end_time_ns is not None
            assert span.duration_ms >= 5  # conservative for CI
        finally:
            _current_tracer.reset(token)

    def test_span_finished_on_exception(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span
            async def failing_func():
                raise ValueError("test error")

            try:
                asyncio.run(failing_func())
            except ValueError:
                pass

            trace = tracer.finish()
            failing_span = [s for s in trace.spans if s.name == "failing_func"][0]
            assert failing_span.end_time_ns is not None
        finally:
            _current_tracer.reset(token)

    def test_nested_decorators(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span
            async def inner():
                return "done"

            @trace_span
            async def outer():
                return await inner()

            result = asyncio.run(outer())
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

    def test_mixed_sync_and_async_nesting(self):
        """A sync-decorated caller invoking an async-decorated callee still links parent/child."""
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span
            async def inner():
                return "done"

            @trace_span
            def outer():
                return asyncio.run(inner())

            result = outer()
            assert result == "done"

            trace = tracer.finish()
            inner_span = [s for s in trace.spans if s.name == "inner"][0]
            outer_span = [s for s in trace.spans if s.name == "outer"][0]
            assert inner_span.parent_span_id == outer_span.span_id
        finally:
            _current_tracer.reset(token)

    def test_current_span_scoped_to_execution(self):
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        captured_span = None
        try:
            assert get_current_span() is None

            @trace_span
            async def observable():
                nonlocal captured_span
                captured_span = get_current_span()

            asyncio.run(observable())
            assert captured_span is not None
            assert captured_span.name == "observable"
            assert get_current_span() is None  # reset after execution
        finally:
            _current_tracer.reset(token)

    def test_concurrent_tasks_have_independent_spans(self):
        """Sibling tasks started with asyncio.gather should each get their own span,
        and neither should leak its span id into the other as a parent."""
        tracer = RequestTracer(operation="root", detector_id="det_1")
        token = _current_tracer.set(tracer)
        try:

            @trace_span
            async def task_a():
                await asyncio.sleep(0.005)
                return get_current_span().span_id

            @trace_span
            async def task_b():
                await asyncio.sleep(0.005)
                return get_current_span().span_id

            async def run_both():
                return await asyncio.gather(task_a(), task_b())

            a_id, b_id = asyncio.run(run_both())
            assert a_id != b_id

            trace = tracer.finish()
            a_span = [s for s in trace.spans if s.name == "task_a"][0]
            b_span = [s for s in trace.spans if s.name == "task_b"][0]
            # Neither sibling should be the other's parent.
            assert a_span.parent_span_id != b_span.span_id
            assert b_span.parent_span_id != a_span.span_id
        finally:
            _current_tracer.reset(token)


class TestGetHelpers:
    def test_defaults_are_none(self):
        assert get_current_tracer() is None
        assert get_current_span() is None
