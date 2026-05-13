"""Per-camera lens client processes.

Three lens types — each entry point is a multiprocessing.Process target.
Every HTTP inference is logged as one JSONL "request" event in the schema
parse_load_test_logs consumes (matches multiple_client_throughput_test.py).

Image strategy (favoring throughput, not realism):
- Each lens pre-encodes a small pool of JPEGs at startup and cycles per frame.
- The downstream binary stage in bbox_to_binary reuses ONE tiny pre-encoded
  JPEG submitted N times per frame — bypasses crop/resize/re-encode entirely.
"""

import json
import os
import sys
import time
from datetime import datetime

import cv2
import image_helpers as imgh
import numpy as np
from groundlight import ExperimentalApi
from groundlight_helpers import error_if_not_from_edge

_JPEG_QUALITY = 90
_BINARY_DOWNSTREAM_SIZE = (224, 224)
_POOL_SIZE = 8


def _encode_jpeg(canvas: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def _build_binary_pool(image_size: tuple[int, int]) -> list[bytes]:
    w, h = image_size
    return [_encode_jpeg(imgh.generate_random_binary_image(w, h)[0]) for _ in range(_POOL_SIZE)]


def _build_objects_pool(image_size: tuple[int, int], max_count: int) -> list[bytes]:
    w, h = image_size
    return [
        _encode_jpeg(imgh.generate_random_objects_image(w, h, max_count=max_count)[0])
        for _ in range(_POOL_SIZE)
    ]


def _submit_and_log(
    gl: ExperimentalApi,
    detector_id: str,
    image_bytes: bytes,
    *,
    log_file: str,
    lens_name: str,
    camera: int,
    worker_number: int,
    request_number: int,
    stage: str | None = None,
) -> None:
    """One submit + one JSONL line. Catches all exceptions; logs success/error."""
    request_start = time.time()
    try:
        iq = gl.ask_ml(detector_id, image_bytes)
        error_if_not_from_edge(iq)
        success = True
        error: str | None = None
    except Exception as exc:  # noqa: BLE001
        success = False
        error = str(exc)
    end = time.time()
    record = {
        "asctime": datetime.fromtimestamp(end).strftime("%Y-%m-%d %H:%M:%S"),
        "ts": end,
        "event": "request",
        "lens_name": lens_name,
        "camera": camera,
        "worker_number": worker_number,
        "request_number": request_number,
        "latency": round(end - request_start, 4),
        "success": success,
    }
    if stage is not None:
        record["stage"] = stage
    if error is not None:
        record["error"] = error
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _silence_stderr() -> None:
    """SDK retry warnings are noisy at high RPS — mute stderr right before the
    per-frame submit loop. Call this *after* SDK init + JPEG pool build so any
    startup failure (bad URL, missing token, image generator error) surfaces
    its traceback to the parent's stderr instead of vanishing into /dev/null."""
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115


def _pace(period: float, frame_start: float) -> None:
    if period <= 0:
        return
    sleep_for = period - (time.time() - frame_start)
    if sleep_for > 0:
        time.sleep(sleep_for)


def run_single_binary(  # noqa: PLR0913
    *,
    worker_number: int,
    camera: int,
    lens_name: str,
    detector_id: str,
    edge_url: str,
    image_size: tuple[int, int],
    target_fps: float,
    duration_seconds: float,
    log_file: str,
) -> None:
    gl = ExperimentalApi(endpoint=edge_url)
    pool = _build_binary_pool(image_size)
    _silence_stderr()
    period = 1.0 / target_fps if target_fps > 0 else 0.0
    deadline = time.time() + duration_seconds
    request_number = 1
    pool_idx = 0
    while time.time() < deadline:
        frame_start = time.time()
        _submit_and_log(
            gl, detector_id, pool[pool_idx],
            log_file=log_file, lens_name=lens_name, camera=camera,
            worker_number=worker_number, request_number=request_number,
        )
        request_number += 1
        pool_idx = (pool_idx + 1) % _POOL_SIZE
        _pace(period, frame_start)


def run_single_bbox(  # noqa: PLR0913
    *,
    worker_number: int,
    camera: int,
    lens_name: str,
    detector_id: str,
    n: int,
    edge_url: str,
    image_size: tuple[int, int],
    target_fps: float,
    duration_seconds: float,
    log_file: str,
) -> None:
    gl = ExperimentalApi(endpoint=edge_url)
    pool = _build_objects_pool(image_size, n)
    _silence_stderr()
    period = 1.0 / target_fps if target_fps > 0 else 0.0
    deadline = time.time() + duration_seconds
    request_number = 1
    pool_idx = 0
    while time.time() < deadline:
        frame_start = time.time()
        _submit_and_log(
            gl, detector_id, pool[pool_idx],
            log_file=log_file, lens_name=lens_name, camera=camera,
            worker_number=worker_number, request_number=request_number,
        )
        request_number += 1
        pool_idx = (pool_idx + 1) % _POOL_SIZE
        _pace(period, frame_start)


def run_bbox_to_binary(  # noqa: PLR0913
    *,
    worker_number: int,
    camera: int,
    lens_name: str,
    bbox_detector_id: str,
    binary_detector_id: str,
    n: int,
    edge_url: str,
    image_size: tuple[int, int],
    target_fps: float,
    duration_seconds: float,
    log_file: str,
) -> None:
    gl = ExperimentalApi(endpoint=edge_url)
    bbox_pool = _build_objects_pool(image_size, n)
    bw, bh = _BINARY_DOWNSTREAM_SIZE
    binary_blob = _encode_jpeg(imgh.generate_random_binary_image(bw, bh)[0])
    _silence_stderr()
    period = 1.0 / target_fps if target_fps > 0 else 0.0
    deadline = time.time() + duration_seconds
    request_number = 1
    pool_idx = 0
    while time.time() < deadline:
        frame_start = time.time()
        _submit_and_log(
            gl, bbox_detector_id, bbox_pool[pool_idx],
            log_file=log_file, lens_name=lens_name, camera=camera,
            worker_number=worker_number, request_number=request_number, stage="bbox",
        )
        request_number += 1
        pool_idx = (pool_idx + 1) % _POOL_SIZE
        for _ in range(n):
            _submit_and_log(
                gl, binary_detector_id, binary_blob,
                log_file=log_file, lens_name=lens_name, camera=camera,
                worker_number=worker_number, request_number=request_number, stage="binary",
            )
            request_number += 1
        _pace(period, frame_start)


LENS_RUNNERS = {
    "single_binary": run_single_binary,
    "single_bbox": run_single_bbox,
    "bbox_to_binary": run_bbox_to_binary,
}
