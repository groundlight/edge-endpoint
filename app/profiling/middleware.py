import logging

from app.profiling import PROFILING_ENABLED, record_trace, start_trace

# Middleware is the sole setter of the tracer context; public API only exposes getters.
from app.profiling.context import _current_tracer

logger = logging.getLogger(__name__)


class ProfilingMiddleware:
    """Raw ASGI middleware that wraps HTTP requests with a profiling trace.

    Uses raw ASGI instead of BaseHTTPMiddleware to avoid issues with streaming
    responses and exception propagation.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not PROFILING_ENABLED:
            return await self.app(scope, receive, send)

        query_string = scope.get("query_string", b"").decode("utf-8", errors="replace")
        detector_id = _parse_detector_id(query_string)

        tracer = start_trace("request", detector_id=detector_id)
        token = _current_tracer.set(tracer)
        try:
            await self.app(scope, receive, send)
        finally:
            try:
                record_trace(tracer.finish())
            except Exception:
                logger.exception("Failed to record profiling trace")
            _current_tracer.reset(token)


def _parse_detector_id(query_string: str) -> str:
    """Extract detector_id from a raw query string."""
    for part in query_string.split("&"):
        if part.startswith("detector_id="):
            return part[len("detector_id=") :]
    return "unknown"
