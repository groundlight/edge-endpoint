from app.profiling.config import PROFILING_ENABLED
from app.profiling.context import get_current_span, get_current_tracer, trace_span

_manager = None


def get_profiling_manager():
    """Returns the ProfilingManager singleton. Only call when PROFILING_ENABLED is True."""
    global _manager
    if _manager is None:
        from app.profiling.manager import ProfilingManager

        _manager = ProfilingManager()
    return _manager


def start_trace(operation: str, detector_id: str):
    """Create and return a new RequestTracer. Only call when PROFILING_ENABLED is True."""
    from app.profiling.tracer import RequestTracer

    return RequestTracer(operation=operation, detector_id=detector_id)


def record_trace(trace):
    """Record a completed trace to disk. Only call when PROFILING_ENABLED is True."""
    get_profiling_manager().record_trace(trace)
