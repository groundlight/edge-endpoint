from dataclasses import dataclass, field


@dataclass(frozen=True)
class FrameEvent:
    """A single event emitted by a client process.

    stage_idx == -1 marks the end-of-frame summary (one per lens-loop iteration).
    stage_idx >= 0 marks a per-stage POST event (latency / retry / error analysis only).
    Per-lens FPS is computed from stage_idx == -1 rows ONLY (see TDD §6.7.1).
    """

    ts: float
    lens_name: str
    client_id: str
    stage_idx: int
    detector_id: str
    latency_ms: float
    http_status: int
    retry_count: int
    was_terminal: bool
    composite_objects_count: int


@dataclass(frozen=True)
class ClientFailedEvent:
    ts: float
    lens_name: str
    client_id: str
    reason: str


@dataclass(frozen=True)
class GpuDeviceSample:
    index: int
    uuid: str | None
    name: str
    vram_used_bytes: int
    vram_total_bytes: int
    compute_pct: float
    memory_bandwidth_pct: float


@dataclass(frozen=True)
class SystemSample:
    ts: float
    cpu_total_pct: float
    ram_used_bytes: int
    ram_total_bytes: int
    gpu_compute_total_pct: float
    gpu_vram_used_bytes: int
    gpu_vram_total_bytes: int
    gpu_devices: list[GpuDeviceSample] = field(default_factory=list)
    loading_detectors_bytes: int = 0
    error: str | None = None
