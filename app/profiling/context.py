import contextvars
from functools import wraps

_current_tracer = contextvars.ContextVar("_current_tracer", default=None)
_current_span = contextvars.ContextVar("_current_span", default=None)


def get_current_tracer():
    """Returns the active RequestTracer for the current context, or None."""
    return _current_tracer.get()


def get_current_span():
    """Returns the active Span for the current context, or None."""
    return _current_span.get()


def trace_span(name):
    """Decorator that creates a child span when a tracer is active.

    When no tracer is set in the context (profiling disabled or outside a traced request),
    the decorated function is called directly with ~50-100ns overhead (one ContextVar.get()).
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            tracer = _current_tracer.get()
            if tracer is None:
                return func(*args, **kwargs)
            current = _current_span.get()
            parent_id = current.span_id if current else None
            span = tracer.start_span(name, parent_span_id=parent_id)
            token = _current_span.set(span)
            try:
                return func(*args, **kwargs)
            finally:
                tracer.end_span(span)
                _current_span.reset(token)

        return wrapper

    return decorator
