from dataclasses import dataclass, field


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_time_ns: int
    end_time_ns: int | None = None
    annotations: dict[str, str] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.end_time_ns is None:
            return -1.0
        return (self.end_time_ns - self.start_time_ns) / 1_000_000

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time_ns": self.start_time_ns,
            "end_time_ns": self.end_time_ns,
            "duration_ms": self.duration_ms,
            "annotations": self.annotations,
        }


@dataclass
class Trace:
    trace_id: str
    detector_id: str
    start_wall_time_iso: str
    spans: list[Span] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "detector_id": self.detector_id,
            "start_wall_time_iso": self.start_wall_time_iso,
            "spans": [s.to_dict() for s in self.spans],
        }
