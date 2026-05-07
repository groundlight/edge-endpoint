"""Per-camera client process: composite generation, chain loop, error budget.

Uses `gl.ask_ml(detector, image)` for every inference — it returns the
first ML prediction without polling for confidence escalation, which is
required when the edge runs in NO_CLOUD mode (submit_image_query would
otherwise round-trip to the (unreachable in our runs) cloud for low-confidence
results).

The SDK handles paths, auth, and 5xx/429 retries internally.
"""

import collections
import logging
import multiprocessing as mp
import time

from app_benchmark.config import LensSpec
from app_benchmark.image_loader import (
    CompositeGenerator,
    GeneratedFrame,
    crop_from_roi,
    load_padding_jpeg,
)
from app_benchmark.ipc import ClientFailedEvent, FrameEvent

logger = logging.getLogger(__name__)


class FpsPacer:
    """Sleeps until the next tick. No-op when target_fps == 0 (saturate)."""

    def __init__(self, target_fps: float) -> None:
        self._period = (1.0 / target_fps) if target_fps > 0 else 0.0
        self._next = time.perf_counter() + self._period

    def wait(self) -> None:
        if self._period == 0.0:
            return
        delay = self._next - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        self._next += self._period
        now = time.perf_counter()
        if self._next < now:
            self._next = now + self._period


class ErrorBudget:
    """Rolling-window error rate. Returns True when error count / total > threshold_pct."""

    def __init__(self, threshold_pct: float, window_s: float = 30.0) -> None:
        self.threshold_pct = threshold_pct
        self.window_s = window_s
        self._events: collections.deque[tuple[float, bool]] = collections.deque()

    def record(self, ts: float, was_error: bool) -> None:
        self._events.append((ts, was_error))
        cutoff = ts - self.window_s
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def exceeded(self) -> bool:
        if len(self._events) < 10:
            return False
        errors = sum(1 for _, e in self._events if e)
        return (errors / len(self._events)) * 100.0 > self.threshold_pct


def run_client(
    client_id: str,
    cam_idx: int,
    lens: LensSpec,
    detector_id_by_name: dict[str, str],
    edge_url: str,
    event_queue: "mp.Queue",
    stop_event,
) -> None:
    """Entry point for a single client process. Runs until stop_event is set."""

    # SDK client constructed *after* fork. Edge endpoint; the edge transparently
    # proxies any cloud-side operations we'd issue, so a single client suffices.
    from groundlight import ExperimentalApi  # noqa: PLC0415

    gl = ExperimentalApi(endpoint=edge_url)

    gen = CompositeGenerator(lens.image, cam_idx)
    is_chained = len(lens.chain) > 1
    if is_chained:
        assert lens.downstream_crop is not None
        crop_w, crop_h = lens.downstream_crop.resize_to
        padding_jpeg = load_padding_jpeg(lens.downstream_crop.padding_image, (crop_w, crop_h))
        max_objects = lens.chain[0].num_crops_into_next
    else:
        crop_w = crop_h = 0
        padding_jpeg = b""
        assert lens.image.composite_objects is not None
        max_objects = lens.image.composite_objects

    pacer = FpsPacer(lens.target_fps)
    error_budget = ErrorBudget(lens.error_budget_pct, window_s=30.0)

    while not stop_event.is_set():
        try:
            frame = gen.next(max_objects=max_objects)
        except Exception as exc:
            logger.exception("composite generation failed",
                             extra={"phase": "run", "lens": lens.name, "client": client_id})
            event_queue.put(ClientFailedEvent(ts=time.time(), lens_name=lens.name,
                                              client_id=client_id, reason=f"composite_failed: {exc}"))
            return

        t0_frame = time.perf_counter()
        try:
            had_any_error = _send_frame(
                gl=gl, lens=lens, detector_id_by_name=detector_id_by_name, frame=frame,
                crop_resize=(crop_w, crop_h), padding_jpeg=padding_jpeg,
                event_queue=event_queue, client_id=client_id,
            )
        except RuntimeError as exc:
            logger.error("fatal error in client loop: %s", exc,
                         extra={"phase": "run", "lens": lens.name, "client": client_id})
            event_queue.put(ClientFailedEvent(ts=time.time(), lens_name=lens.name,
                                              client_id=client_id, reason=str(exc)))
            return

        latency_ms = (time.perf_counter() - t0_frame) * 1000.0
        ts = time.time()
        event_queue.put(FrameEvent(
            ts=ts,
            lens_name=lens.name,
            client_id=client_id,
            stage_idx=-1,
            detector_id="",
            latency_ms=latency_ms,
            http_status=200 if not had_any_error else 0,
            retry_count=0,
            was_terminal=True,
            composite_objects_count=frame.composite_objects_count,
        ))
        error_budget.record(ts, had_any_error)
        if error_budget.exceeded():
            logger.error("error budget exceeded for client %s; exiting", client_id,
                         extra={"phase": "run", "lens": lens.name, "client": client_id})
            event_queue.put(ClientFailedEvent(ts=ts, lens_name=lens.name,
                                              client_id=client_id, reason="error_budget_exceeded"))
            return

        pacer.wait()


def _submit_via_sdk(gl, detector_id: str, image_bytes: bytes) -> tuple[bool, bool]:
    """Submit one inference via gl.ask_ml. Returns (was_error, fatal).

    ask_ml is preferred over submit_image_query in NO_CLOUD mode: it returns
    the first ML prediction without polling for high-confidence escalation,
    which would otherwise round-trip to the cloud and fail.

    fatal=True means we observed a control-plane drift (cloud fallback) or an
    unrecoverable error from the SDK after its built-in retries — caller
    should propagate as RuntimeError to terminate the run.
    """
    try:
        iq = gl.ask_ml(detector_id, image_bytes)
    except Exception as exc:
        # SDK handles 5xx/429 retry internally; this catches exhausted retries
        # and any unhandled API error. Treat as a non-fatal error event.
        logger.warning("SDK ask_ml failed for %s: %s", detector_id, exc)
        return True, False

    result = getattr(iq, "result", None)
    from_edge = getattr(result, "from_edge", None)
    if from_edge is False:
        return True, True  # control-plane drift → fatal
    return False, False


def _send_frame(
    *,
    gl,
    lens: LensSpec,
    detector_id_by_name: dict[str, str],
    frame: GeneratedFrame,
    crop_resize: tuple[int, int],
    padding_jpeg: bytes,
    event_queue: "mp.Queue",
    client_id: str,
) -> bool:
    """Run the chain for one frame. Returns True if any non-fatal error occurred."""
    had_error = False
    is_chained = len(lens.chain) > 1

    # Stage 0: composite to upstream detector.
    stage_0 = lens.chain[0]
    det_id = detector_id_by_name[stage_0.detector]
    t0 = time.perf_counter()
    was_error, fatal = _submit_via_sdk(gl, det_id, frame.canvas_jpeg)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    event_queue.put(FrameEvent(
        ts=time.time(), lens_name=lens.name, client_id=client_id, stage_idx=0,
        detector_id=det_id, latency_ms=elapsed_ms,
        http_status=200 if not was_error else 0,
        retry_count=0, was_terminal=not is_chained,
        composite_objects_count=frame.composite_objects_count,
    ))
    if fatal:
        raise RuntimeError(f"control-plane drift on stage 0 for {det_id}")
    if was_error:
        had_error = True
    if not is_chained:
        return had_error

    # Build the downstream batch from generation ground truth + padding.
    n_target = stage_0.num_crops_into_next
    crops: list[bytes] = []
    for i in range(n_target):
        if i < len(frame.rois):
            crops.append(crop_from_roi(frame.canvas_jpeg, frame.rois[i], crop_resize))
        else:
            crops.append(padding_jpeg)

    # Stages 1..N. v1 chains are typically 2-stage (bbox -> binary).
    for stage_idx in range(1, len(lens.chain)):
        stage = lens.chain[stage_idx]
        is_terminal = stage_idx == len(lens.chain) - 1
        det_id = detector_id_by_name[stage.detector]
        for crop in crops:
            t0 = time.perf_counter()
            was_error, fatal = _submit_via_sdk(gl, det_id, crop)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            event_queue.put(FrameEvent(
                ts=time.time(), lens_name=lens.name, client_id=client_id, stage_idx=stage_idx,
                detector_id=det_id, latency_ms=elapsed_ms,
                http_status=200 if not was_error else 0,
                retry_count=0, was_terminal=is_terminal,
                composite_objects_count=frame.composite_objects_count,
            ))
            if fatal:
                raise RuntimeError(f"control-plane drift on stage {stage_idx} for {det_id}")
            if was_error:
                had_error = True

    return had_error
