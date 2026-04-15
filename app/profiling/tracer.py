import threading
import time
import uuid
from datetime import datetime, timezone

from app.profiling.models import Span, Trace


class RequestTracer:
    """Traces a single request through the inference pipeline. Thread-safe."""

    def __init__(self, operation: str, detector_id: str):
        self.trace = Trace(
            trace_id=uuid.uuid4().hex,
            detector_id=detector_id,
            start_wall_time_iso=datetime.now(timezone.utc).isoformat(),
        )
        self._lock = threading.Lock()
        self._root_span = self._create_span(operation, parent_span_id=None)

    def _create_span(self, name: str, parent_span_id: str | None) -> Span:
        span = Span(
            name=name,
            trace_id=self.trace.trace_id,
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=parent_span_id,
            start_time_ns=time.perf_counter_ns(),
        )
        with self._lock:
            self.trace.spans.append(span)
        return span

    def start_span(self, name: str, parent_span_id: str | None = None) -> Span:
        """Start a new child span. If parent_span_id is None, parents to root."""
        pid = parent_span_id or self._root_span.span_id
        return self._create_span(name, parent_span_id=pid)

    def end_span(self, span: Span, **annotations: str) -> None:
        """End a span and attach any annotations."""
        span.end_time_ns = time.perf_counter_ns()
        if annotations:
            span.annotations.update(annotations)

    def annotate(self, span: Span, **kv: str) -> None:
        """Add key-value annotations to a span."""
        span.annotations.update(kv)

    def finish(self) -> Trace:
        """End the root span and return the completed trace."""
        self._root_span.end_time_ns = time.perf_counter_ns()
        return self.trace

    @property
    def trace_id(self) -> str:
        return self.trace.trace_id

    @property
    def root_span_id(self) -> str:
        return self._root_span.span_id
