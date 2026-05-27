"""Per-camera lens client processes.

Three lens types — each entry point is a multiprocessing.Process target.
Every HTTP inference is logged as one JSONL "request" event in the schema
parse_load_test_logs consumes (matches multiple_client_throughput_test.py).

Image strategy: generate a fresh ndarray per frame from the helpers in
load-testing/image_helpers.py and pass it straight to the Groundlight SDK
(`ask_ml` accepts np.ndarray and handles JPEG encoding internally). For the
chained `bbox_to_binary` lens, the small downstream binary image is built
once at lens startup and re-submitted N times per frame — the SDK
re-encodes per call, which at 224x224 is negligible.
"""

import json
import os
import sys
import time
from datetime import datetime

import image_helpers as imgh
from groundlight import ExperimentalApi
from groundlight_helpers import error_if_not_from_edge

from app_benchmark.constants import BINARY_DOWNSTREAM_SIZE


def _submit_and_log(
    gl: ExperimentalApi,
    detector_id: str,
    image,  # np.ndarray; SDK does the JPEG encode
    *,
    log_handle,
    lens_name: str,
    camera: int,
    worker_number: int,
    request_number: int,
    stage: str | None = None,
) -> None:
    """Submit one inference, time it, write one JSONL line to log_handle.

    Catches every exception so a single request failure doesn't kill the
    worker; the failure is recorded as `success: false` in the log and
    rolls up into the run's error count. The SDK retries 5xx/429
    internally before bubbling up, so anything we catch here has already
    exhausted the SDK's backoff.

    Args:
        gl: SDK client pointed at the edge endpoint.
        detector_id: Target detector for this request.
        image: np.ndarray passed directly to ask_ml; the SDK encodes it.
        log_handle: Open, line-buffered file handle to write to. The
            runner opens it once at startup (one log file per camera
            process) and closes it on exit.
        lens_name: Identifies the lens in the log (and the report).
        camera: Per-lens camera index (0..lens.cameras-1).
        worker_number: Global worker index across all lenses, useful for
            cross-process tagging.
        request_number: Monotonic counter within this worker — useful
            when diffing logs.
        stage: Optional "bbox" or "binary" tag for chained lenses;
            single-stage lenses leave this None. The report keys frame
            counting off the absence of `stage` OR `stage == "bbox"`.
    """
    request_start = time.time()
    try:
        iq = gl.ask_ml(detector_id, image)
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
    log_handle.write(json.dumps(record) + "\n")


def _silence_stderr() -> None:
    """SDK retry warnings are noisy at high RPS — mute stderr right before the
    per-frame submit loop. Call this *after* SDK init so any startup failure
    (bad URL, missing token, etc.) surfaces its traceback to the parent."""
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115


def _pace(period: float, frame_start: float) -> None:
    """Sleep just long enough to maintain `period` between frame starts.
    No-op when `period <= 0` (saturate mode)."""
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
    """multiprocessing.Process target for a `single_binary` lens worker.

    Generates a fresh random binary image (black/white with timestamp
    overlay) per frame and submits one inference. Loops until
    `duration_seconds` elapses.

    Args:
        worker_number: Global worker index, recorded on every log line.
        camera: This worker's per-lens camera index.
        lens_name: Logged on every event; matched against config in the
            report.
        detector_id: Cloud detector ID for the binary inference.
        edge_url: Edge endpoint URL; the SDK client is built from this.
        image_size: (width, height) of the synthetic image to generate.
        target_fps: Per-frame pace target. 0 = saturate (no sleep
            between frames).
        duration_seconds: How long this worker runs before exiting.
        log_file: Append-only JSONL log path; one file per camera process
            (the runner opens it once and writes for its whole lifetime).
    """
    gl = ExperimentalApi(endpoint=edge_url)
    w, h = image_size
    _silence_stderr()
    period = 1.0 / target_fps if target_fps > 0 else 0.0
    deadline = time.time() + duration_seconds
    request_number = 1
    # Per-camera log file: opened once, line-buffered so events flush per
    # write without an explicit fsync. Closed automatically on `with` exit.
    with open(log_file, "a", buffering=1, encoding="utf-8") as log:
        while time.time() < deadline:
            frame_start = time.time()
            image, _, _ = imgh.generate_random_binary_image(w, h)
            _submit_and_log(
                gl, detector_id, image,
                log_handle=log, lens_name=lens_name, camera=camera,
                worker_number=worker_number, request_number=request_number,
            )
            request_number += 1
            _pace(period, frame_start)


def run_single_bbox(  # noqa: PLR0913
    *,
    worker_number: int,
    camera: int,
    lens_name: str,
    detector_id: str,
    objects: int,
    edge_url: str,
    image_size: tuple[int, int],
    target_fps: float,
    duration_seconds: float,
    log_file: str,
) -> None:
    """multiprocessing.Process target for a `single_bbox` lens worker.

    Generates a fresh image containing exactly `objects` placed entities
    per frame (via image_helpers.generate_fixed_objects_image) and
    submits one bounding-box inference.

    Args:
        worker_number: Global worker index, recorded on every log line.
        camera: This worker's per-lens camera index.
        lens_name: Logged on every event; matched against config in the
            report.
        detector_id: Cloud detector ID for the bbox inference.
        objects: Exact object count placed in each synthesized image for
            this run. The detector itself was provisioned once with
            max_num_bboxes = max(lens.objects), so the per-run value
            only changes the image content (and any downstream cost on
            the model that scales with detected count).
        edge_url: Edge endpoint URL; the SDK client is built from this.
        image_size: (width, height) of the synthetic image to generate.
        target_fps: Per-frame pace target. 0 = saturate.
        duration_seconds: How long this worker runs before exiting.
        log_file: Append-only JSONL log path; one file per camera process
            (the runner opens it once and writes for its whole lifetime).
    """
    gl = ExperimentalApi(endpoint=edge_url)
    w, h = image_size
    _silence_stderr()
    period = 1.0 / target_fps if target_fps > 0 else 0.0
    deadline = time.time() + duration_seconds
    request_number = 1
    with open(log_file, "a", buffering=1, encoding="utf-8") as log:
        while time.time() < deadline:
            frame_start = time.time()
            image, _, _ = imgh.generate_fixed_objects_image(w, h, count=objects)
            _submit_and_log(
                gl, detector_id, image,
                log_handle=log, lens_name=lens_name, camera=camera,
                worker_number=worker_number, request_number=request_number,
            )
            request_number += 1
            _pace(period, frame_start)


def run_bbox_to_binary(  # noqa: PLR0913
    *,
    worker_number: int,
    camera: int,
    lens_name: str,
    bbox_detector_id: str,
    binary_detector_id: str,
    objects: int,
    edge_url: str,
    image_size: tuple[int, int],
    target_fps: float,
    duration_seconds: float,
    log_file: str,
) -> None:
    """multiprocessing.Process target for a `bbox_to_binary` lens worker.

    Per frame:
      1. Generate a fresh `image_size` image with exactly `objects`
         placed entities (via image_helpers.generate_fixed_objects_image)
         and submit one bbox inference (logged with stage=bbox).
      2. Submit a cached small (224x224) binary image `objects` times
         in a row (each logged with stage=binary).

    The cached downstream image is generated once at worker startup; the
    SDK re-encodes it per call, which at 224x224 is cheap.

    Args:
        worker_number: Global worker index, recorded on every log line.
        camera: This worker's per-lens camera index.
        lens_name: Logged on every event; matched against config in the
            report.
        bbox_detector_id: Cloud detector ID for the upstream bbox stage.
        binary_detector_id: Cloud detector ID for the downstream binary
            stage.
        objects: Both the exact object count placed in the bbox image
            AND the number of downstream binary calls issued per frame.
        edge_url: Edge endpoint URL; the SDK client is built from this.
        image_size: (width, height) of the upstream bbox image.
        target_fps: Per-frame pace target (one frame = 1 bbox +
            `objects` binary calls). 0 = saturate.
        duration_seconds: How long this worker runs before exiting.
        log_file: Append-only JSONL log path; one file per camera process
            (the runner opens it once and writes for its whole lifetime).
    """
    gl = ExperimentalApi(endpoint=edge_url)
    w, h = image_size
    bw, bh = BINARY_DOWNSTREAM_SIZE
    # One small binary image, reused for every downstream call. The SDK
    # encodes each request, but 224x224 encoding is cheap (~ms).
    binary_image, _, _ = imgh.generate_random_binary_image(bw, bh)
    _silence_stderr()
    period = 1.0 / target_fps if target_fps > 0 else 0.0
    deadline = time.time() + duration_seconds
    request_number = 1
    with open(log_file, "a", buffering=1, encoding="utf-8") as log:
        while time.time() < deadline:
            frame_start = time.time()
            bbox_image, _, _ = imgh.generate_fixed_objects_image(w, h, count=objects)
            _submit_and_log(
                gl, bbox_detector_id, bbox_image,
                log_handle=log, lens_name=lens_name, camera=camera,
                worker_number=worker_number, request_number=request_number, stage="bbox",
            )
            request_number += 1
            for _ in range(objects):
                _submit_and_log(
                    gl, binary_detector_id, binary_image,
                    log_handle=log, lens_name=lens_name, camera=camera,
                    worker_number=worker_number, request_number=request_number, stage="binary",
                )
                request_number += 1
            _pace(period, frame_start)


LENS_RUNNERS = {
    "single_binary": run_single_binary,
    "single_bbox": run_single_bbox,
    "bbox_to_binary": run_bbox_to_binary,
}
