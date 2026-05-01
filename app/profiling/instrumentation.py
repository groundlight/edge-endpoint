"""Runtime instrumentation that closes profiling gaps the @trace_span decorator can't reach.

Currently this module only handles `starlette.concurrency.run_in_threadpool`. FastAPI dispatches every
synchronous dependency and Starlette dispatches every synchronous BackgroundTask through that helper,
which awaits an `anyio` worker thread. When the anyio threadpool (default 40 workers per process) is
saturated under load, the awaiting coroutine sits in the queue. `@trace_span` on the dispatched function
only times the function's actual execution inside the worker - the wait time vanishes into untraced gaps
in the waterfall.

`install_threadpool_tracing()` wraps each binding of `run_in_threadpool` so the wait+execute interval is
captured as a parent span named `run_in_threadpool[<funcname>]`. The dispatched function's own
`@trace_span` (if present) still fires inside the worker thread and becomes a child span; the difference
between the two spans' durations is the threadpool wait time.
"""

import functools
from collections.abc import Awaitable, Callable
from typing import Any

import fastapi.dependencies.utils
import starlette.background
import starlette.concurrency

from app.profiling.context import _current_span, _current_tracer

_PATCHED_MARKER = "_groundlight_profiling_patched"


def _make_traced(original: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Wrap an async run_in_threadpool implementation so wait+execute time becomes a span."""

    @functools.wraps(original)
    async def traced(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        tracer = _current_tracer.get()
        if tracer is None:
            return await original(func, *args, **kwargs)
        current = _current_span.get()
        parent_id = current.span_id if current else None
        name = f"run_in_threadpool[{getattr(func, '__name__', 'fn')}]"
        span = tracer.start_span(name, parent_span_id=parent_id)
        token = _current_span.set(span)
        try:
            return await original(func, *args, **kwargs)
        finally:
            tracer.end_span(span)
            _current_span.reset(token)

    setattr(traced, _PATCHED_MARKER, True)
    return traced


def install_threadpool_tracing() -> None:
    """Monkey-patch every known binding of run_in_threadpool to record the wait+execute span.

    Idempotent: a second call is a no-op. Safe to call before the first request is served.
    """
    if getattr(starlette.concurrency.run_in_threadpool, _PATCHED_MARKER, False):
        return
    traced = _make_traced(starlette.concurrency.run_in_threadpool)
    starlette.concurrency.run_in_threadpool = traced
    fastapi.dependencies.utils.run_in_threadpool = traced
    starlette.background.run_in_threadpool = traced
