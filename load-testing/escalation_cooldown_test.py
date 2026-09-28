"""
Measure how often two edge detectors escalate when queried faster than the cooldown.

Provisions two BOUNDING_BOX detectors, sets each confidence threshold to 1.0, and
loads them on the edge with an InferenceConfig that always returns the edge answer
and uses --min-time-between-escalations as the cooldown. Then it submits image
queries as fast as one thread can, alternating detectors, for --duration seconds.
Escalations are cloud image queries created at or after the submit loop starts.
The edge uploads those through a queue, so the script waits until the cloud
count stops rising before it computes the rate.

Reads GROUNDLIGHT_API_TOKEN from the environment.
GROUNDLIGHT_ENDPOINT should point at the Edge Endpoint (e.g. https://localhost:30143).
Run from the load-testing directory.
"""
import argparse
import time
from datetime import datetime, timezone
from itertools import cycle

from groundlight import ExperimentalApi, ImageQuery
from groundlight.edge import InferenceConfig

import groundlight_helpers as glh
import image_helpers as imgh

IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480
CONFIDENCE_THRESHOLD = 1.0
DETECTOR_GROUP = "Escalation Cooldown"
DETECTOR_PREFIXES = ("Escalation Cooldown A", "Escalation Cooldown B")
PAGE_SIZE = 100
LIST_POLL_SEC = 2.0
LIST_STABLE_SEC = 6.0
LIST_TIMEOUT_SEC = 90.0
PROGRESS_INTERVAL_SEC = 5.0


def provision_bounding_box_detectors(gl_cloud: ExperimentalApi) -> list:
    """Get or create two BOUNDING_BOX detectors and wait until both have trained."""
    detectors = []
    for prefix in DETECTOR_PREFIXES:
        detector = glh.provision_detector(
            gl_cloud,
            detector_mode="BOUNDING_BOX",
            detector_name_prefix=prefix,
            image_width=IMAGE_WIDTH,
            image_height=IMAGE_HEIGHT,
            group_name=DETECTOR_GROUP,
            wait_for_training=False,
        )
        print(f"Got or created {detector.id} ({detector.name})")
        detectors.append(detector)

    print(f"\n=== Waiting for {len(detectors)} detector(s) to finish training ===")
    for detector in detectors:
        num_labels = glh.num_priming_labels_for_detector(detector)
        min_training_labels = int(num_labels * 0.75)
        glh.wait_for_edge_pipeline_trained(
            gl_cloud, detector, min_training_labels, timeout_sec=glh.DEFAULT_TRAINING_SEC_TIMEOUT
        )
    return detectors


def as_utc(dt: datetime) -> datetime:
    """Return `dt` as a timezone-aware UTC datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_edge_audit(iq: ImageQuery) -> bool:
    """Return True when this cloud image query is a confident-edge audit."""
    metadata = iq.metadata
    if not isinstance(metadata, dict):
        return False
    return bool(metadata.get("is_edge_audit"))


def escalations_since(gl_cloud: ExperimentalApi, detector_id: str, since: datetime) -> list[ImageQuery]:
    """Return non-audit cloud image queries for this detector created at or after `since`.

    The list endpoint is newest-first, so paging stops at the first query older than the window.
    """
    found: list[ImageQuery] = []
    page = 1
    while True:
        batch = gl_cloud.list_image_queries(page=page, page_size=PAGE_SIZE, detector_id=detector_id)
        results = list(batch.results or [])
        if not results:
            break
        reached_older = False
        for iq in results:
            if as_utc(iq.created_at) < since:
                reached_older = True
                continue
            if not is_edge_audit(iq):
                found.append(iq)
        if reached_older or len(results) < PAGE_SIZE:
            break
        page += 1
    return found


def wait_for_escalation_counts(
    gl_cloud: ExperimentalApi, detector_ids: list[str], since: datetime
) -> dict[str, int]:
    """Poll cloud until each detector's escalation count is unchanged for a few seconds.

    The edge writes escalations to a queue and uploads them one at a time, so the cloud count
    keeps rising for a bit after the submit loop stops.
    """
    print("Waiting for escalations to show up in cloud...")
    previous: dict[str, int] | None = None
    unchanged_since: float | None = None
    deadline = time.monotonic() + LIST_TIMEOUT_SEC
    latest = {detector_id: 0 for detector_id in detector_ids}
    while time.monotonic() < deadline:
        latest = {detector_id: len(escalations_since(gl_cloud, detector_id, since)) for detector_id in detector_ids}
        print("  " + ", ".join(f"{detector_id}={count}" for detector_id, count in latest.items()))
        if latest == previous:
            if unchanged_since is None:
                unchanged_since = time.monotonic()
            elif time.monotonic() - unchanged_since >= LIST_STABLE_SEC:
                return latest
        else:
            previous = latest
            unchanged_since = None
        time.sleep(LIST_POLL_SEC)
    print(f"Cloud escalation count was still changing after {LIST_TIMEOUT_SEC:.0f}s; using the last read.")
    return latest


def submit_alternating(
    gl: ExperimentalApi, detectors: list, images: list, duration_sec: float
) -> tuple[int, int]:
    """Submit one image query at a time, alternating detectors, until `duration_sec` elapses.

    Returns the number of successful submissions and the number of errors.
    """
    submitted = 0
    errors = 0
    start = time.monotonic()
    deadline = start + duration_sec
    last_report = start
    for detector, image in cycle(zip(detectors, images)):
        if time.monotonic() >= deadline:
            break
        try:
            gl.submit_image_query(detector, image, wait=0.0, human_review="NEVER")
            submitted += 1
        except Exception as e:
            errors += 1
            print(f"  submit error for {detector.id}: {e}")
        now = time.monotonic()
        if now - last_report >= PROGRESS_INTERVAL_SEC:
            elapsed = now - start
            print(f"[{elapsed:5.0f}s] submitted={submitted} errors={errors} ({submitted / elapsed:.1f}/s)")
            last_report = now
    return submitted, errors


def main() -> None:
    """Provision the detectors, flood them, and print escalations per second."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Seconds to spend submitting image queries (default: 30).",
    )
    parser.add_argument(
        "--min-time-between-escalations",
        type=float,
        default=2.0,
        help="Seconds between cloud escalations for each detector (default: 2).",
    )
    args = parser.parse_args()
    if args.duration <= 0:
        raise SystemExit("--duration must be positive.")
    if args.min_time_between_escalations <= 0:
        raise SystemExit("--min-time-between-escalations must be positive.")

    edge_inference_config = InferenceConfig(
        name="escalation_cooldown",
        always_return_edge_prediction=True,
        min_time_between_escalations=args.min_time_between_escalations,
    )

    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    gl_cloud = ExperimentalApi(endpoint=glh.CLOUD_ENDPOINT_PROD)

    detectors = provision_bounding_box_detectors(gl_cloud)
    for detector in detectors:
        gl_cloud.update_detector_confidence_threshold(detector, CONFIDENCE_THRESHOLD)
        print(f"Set {detector.id} confidence threshold to {CONFIDENCE_THRESHOLD}")

    glh.configure_edge_endpoint(gl, detectors, edge_inference_config=edge_inference_config)

    images = []
    for detector in detectors:
        image, _, _ = imgh.generate_random_image(detector, IMAGE_WIDTH, IMAGE_HEIGHT)
        images.append(image)

    interval = edge_inference_config.min_time_between_escalations
    print(
        f"\n=== Submitting for {args.duration:.0f}s, alternating {len(detectors)} detectors "
        f"(cooldown {interval:.1f}s each) ==="
    )
    window_start = datetime.now(timezone.utc)
    submitted, errors = submit_alternating(gl, detectors, images, args.duration)
    elapsed = (datetime.now(timezone.utc) - window_start).total_seconds()

    counts = wait_for_escalation_counts(gl_cloud, [detector.id for detector in detectors], window_start)
    total = sum(counts.values())

    print(f"\n=== Escalations over {elapsed:.1f}s ===")
    print(f"submitted={submitted} errors={errors} ({submitted / elapsed:.1f} queries/s)")
    for detector in detectors:
        count = counts[detector.id]
        print(f"{detector.id}: {count} escalations ({count / elapsed:.3f}/s)")
    print(f"combined: {total} escalations ({total / elapsed:.3f}/s)")
    print(
        f"min_time_between_escalations={interval:.1f}s, "
        f"so each detector should land near {1 / interval:.3f}/s when queries are faster than the cooldown."
    )


if __name__ == "__main__":
    main()
