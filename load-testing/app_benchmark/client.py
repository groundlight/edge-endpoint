"""Per-camera client process: composite generation, chain loop, retry, error budget."""

import collections
import logging
import multiprocessing as mp
import os
import time

import requests

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
        # Drift correction: never let us fall infinitely behind.
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


_IMAGE_QUERIES_PATH = "/device-api/v1/image-queries"


def _post_image_query(
    session: requests.Session,
    edge_url: str,
    detector_id: str,
    image_bytes: bytes,
    timeout: float = 30.0,
) -> tuple[int, dict | None]:
    url = f"{edge_url.rstrip('/')}{_IMAGE_QUERIES_PATH}"
    params = {"detector_id": detector_id, "want_async": "false"}
    headers = {
        "Content-Type": "image/jpeg",
        "X-API-Token": os.environ.get("GROUNDLIGHT_API_TOKEN", ""),
    }
    resp = session.post(url, params=params, data=image_bytes, headers=headers, timeout=timeout)
    body: dict | None = None
    if resp.headers.get("Content-Type", "").startswith("application/json"):
        try:
            body = resp.json()
        except Exception:
            body = None
    return resp.status_code, body


def _post_with_retry(
    session: requests.Session,
    edge_url: str,
    detector_id: str,
    image_bytes: bytes,
    *,
    max_attempts: int = 3,
    backoffs: tuple[float, ...] = (0.1, 1.0, 5.0),
) -> tuple[int, int, bool]:
    """Returns (final_status, retry_count, fatal_4xx). fatal_4xx=True for 4xx other than 429."""
    last_status = 0
    retries = 0
    for attempt in range(max_attempts):
        try:
            status, body = _post_image_query(session, edge_url, detector_id, image_bytes)
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.debug("connection error on %s: %s", detector_id, exc)
            status = 599
            body = None
        last_status = status
        if 200 <= status < 300:
            if body is not None:
                from_edge = (body.get("result") or {}).get("from_edge")
                if from_edge is False:
                    raise RuntimeError(
                        f"control-plane drift: from_edge=False for {detector_id}; aborting run"
                    )
            return status, retries, False
        if 400 <= status < 500 and status != 429:
            return status, retries, True
        # 5xx, 429, connection error → retry with backoff
        retries += 1
        if attempt + 1 < max_attempts:
            time.sleep(backoffs[min(attempt, len(backoffs) - 1)])
    return last_status, retries, False


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
    session = requests.Session()

    while not stop_event.is_set():
        try:
            frame = gen.next(max_objects=max_objects)
        except Exception as exc:
            logger.exception("composite generation failed: %s", exc,
                             extra={"phase": "run", "lens": lens.name, "client": client_id})
            event_queue.put(ClientFailedEvent(ts=time.time(), lens_name=lens.name,
                                              client_id=client_id, reason=f"composite_failed: {exc}"))
            return

        t0_frame = time.perf_counter()
        try:
            had_any_error = _send_frame(
                session, edge_url, lens, detector_id_by_name, frame,
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
            http_status=0,
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


def _send_frame(
    session: requests.Session,
    edge_url: str,
    lens: LensSpec,
    detector_id_by_name: dict[str, str],
    frame: GeneratedFrame,
    *,
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
    status, retries, fatal = _post_with_retry(session, edge_url, det_id, frame.canvas_jpeg)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    event_queue.put(FrameEvent(
        ts=time.time(), lens_name=lens.name, client_id=client_id, stage_idx=0,
        detector_id=det_id, latency_ms=elapsed_ms, http_status=status,
        retry_count=retries, was_terminal=not is_chained,
        composite_objects_count=frame.composite_objects_count,
    ))
    if fatal:
        raise RuntimeError(f"fatal {status} from upstream stage {det_id}")
    if status >= 400:
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

    # Stages 1..N. v1 chains are typically 2-stage (bbox -> binary); for deeper
    # chains we feed the same crops through each downstream stage.
    for stage_idx in range(1, len(lens.chain)):
        stage = lens.chain[stage_idx]
        is_terminal = stage_idx == len(lens.chain) - 1
        det_id = detector_id_by_name[stage.detector]
        for crop in crops:
            t0 = time.perf_counter()
            status, retries, fatal = _post_with_retry(session, edge_url, det_id, crop)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            event_queue.put(FrameEvent(
                ts=time.time(), lens_name=lens.name, client_id=client_id, stage_idx=stage_idx,
                detector_id=det_id, latency_ms=elapsed_ms, http_status=status,
                retry_count=retries, was_terminal=is_terminal,
                composite_objects_count=frame.composite_objects_count,
            ))
            if fatal:
                raise RuntimeError(f"fatal {status} from stage {stage_idx} {det_id}")
            if status >= 400:
                had_error = True

    return had_error
