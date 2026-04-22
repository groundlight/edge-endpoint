import logging
import time

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

        # Wrap `send` to capture the wall-clock time at which the response is fully flushed to the
        # client. Anything in the request span past this point (e.g. BackgroundTasks) is "behind"
        # the user-visible latency and should be analyzed separately.
        response_sent_ns: list[int] = []

        async def traced_send(message):
            await send(message)
            if (
                not response_sent_ns
                and message.get("type") == "http.response.body"
                and not message.get("more_body", False)
            ):
                response_sent_ns.append(time.perf_counter_ns())

        try:
            await self.app(scope, receive, traced_send)
        finally:
            if response_sent_ns:
                root = tracer.root_span
                root.annotations["response_sent_ms"] = (
                    f"{(response_sent_ns[0] - root.start_time_ns) / 1_000_000:.2f}"
                )
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
