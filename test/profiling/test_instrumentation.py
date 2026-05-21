import asyncio

import fastapi.dependencies.utils
import starlette.background
import starlette.concurrency

from app.profiling.context import _current_tracer, trace_span
from app.profiling.instrumentation import _PATCHED_MARKER, install_threadpool_tracing
from app.profiling.tracer import RequestTracer

# Patch once at import time so behavioral tests work regardless of execution order.
install_threadpool_tracing()


class TestInstallThreadpoolTracing:
    def test_all_known_bindings_are_patched(self):
        """After install, all three module-level bindings should point at the same patched function.

        Regression guard: if a future Starlette/FastAPI release moves run_in_threadpool to a
        different import path, this test will catch it before production silently loses spans.
        """
        install_threadpool_tracing()
        patched = starlette.concurrency.run_in_threadpool
        assert getattr(patched, _PATCHED_MARKER, False), "starlette.concurrency binding is not patched"
        assert fastapi.dependencies.utils.run_in_threadpool is patched
        assert starlette.background.run_in_threadpool is patched

    def test_idempotent(self):
        """Calling install_threadpool_tracing() twice is a no-op; the binding doesn't change."""
        install_threadpool_tracing()
        first_fn = starlette.concurrency.run_in_threadpool
        install_threadpool_tracing()
        assert starlette.concurrency.run_in_threadpool is first_fn

    def test_noop_when_no_tracer(self):
        """The patched run_in_threadpool passes through cleanly when no tracer is in context."""
        call_count = 0

        def sync_work():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = asyncio.run(starlette.concurrency.run_in_threadpool(sync_work))
        assert result == "ok"
        assert call_count == 1

    def test_creates_span_when_tracer_active(self):
        """run_in_threadpool creates a span covering wait+execute time when a tracer is active."""
        tracer = RequestTracer(operation="root", detector_id="det_test")
        token = _current_tracer.set(tracer)
        try:

            def sync_work():
                return 42

            result = asyncio.run(starlette.concurrency.run_in_threadpool(sync_work))
            assert result == 42

            trace = tracer.finish()
            span_names = [s.name for s in trace.spans]
            assert "run_in_threadpool[sync_work]" in span_names
        finally:
            _current_tracer.reset(token)

    def test_inner_trace_span_is_child(self):
        """A @trace_span function dispatched via run_in_threadpool becomes a child of the outer span."""
        tracer = RequestTracer(operation="root", detector_id="det_test")
        token = _current_tracer.set(tracer)
        try:

            @trace_span
            def inner_work():
                return "done"

            asyncio.run(starlette.concurrency.run_in_threadpool(inner_work))
            trace = tracer.finish()

            outer_span = next(s for s in trace.spans if s.name == "run_in_threadpool[inner_work]")
            inner_span = next(s for s in trace.spans if s.name == "inner_work")
            assert inner_span.parent_span_id == outer_span.span_id
        finally:
            _current_tracer.reset(token)

    def test_span_finished_on_exception(self):
        """The run_in_threadpool span is closed even when the dispatched function raises."""
        tracer = RequestTracer(operation="root", detector_id="det_test")
        token = _current_tracer.set(tracer)
        try:

            def failing_work():
                raise ValueError("boom")

            try:
                asyncio.run(starlette.concurrency.run_in_threadpool(failing_work))
            except ValueError:
                pass

            trace = tracer.finish()
            outer_span = next(s for s in trace.spans if s.name == "run_in_threadpool[failing_work]")
            assert outer_span.end_time_ns is not None
        finally:
            _current_tracer.reset(token)
