"""Test that inference works correctly immediately after a fresh pod rollout.

Configures a placeholder detector first, waits for its pod to be ready,
then swaps to the real detector under test. This guarantees the real
detector's pod goes through a complete fresh rollout on every run:
  - While the placeholder is active, any pre-existing pod for the real
    detector is fully evicted.
  - When configuration finishes applying for the real detector, the pod
    has just become ready for the first time this run.

Immediately after that second configuration is applied, the script hammers
the real detector with inference requests as fast as possible for
VICTORY_DURATION_SEC seconds. SDK and transport retries are both disabled
so any transient 5xx errors surface immediately.

Declares victory if no errors occur; otherwise reports all failures and
exits with a non-zero status.
"""
import time

from groundlight import Groundlight, ExperimentalApi, ApiException

import groundlight_helpers as glh
import image_helpers as imgh

VICTORY_DURATION_SEC = 10.0


def main() -> None:
    """Run the fresh-pod readiness check against the configured Edge Endpoint."""
    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    gl_cloud = Groundlight(endpoint=glh.CLOUD_ENDPOINT_PROD)

    # Disable retries so any "no pod available" errors propagate immediately.
    glh.disable_all_retries(gl)

    detector = glh.provision_detector(
        gl_cloud,
        "BINARY",
        "Set Config Readiness Bug Repro",
        group_name="Edge Endpoint Load Testing",
    )
    placeholder_detector = glh.provision_detector(
        gl_cloud,
        "BINARY",
        "Set Config Readiness Bug Repro Placeholder",
        group_name="Edge Endpoint Load Testing",
    )

    # Configure the placeholder and wait for it to be ready. At that point
    # the real detector's pod has been evicted (it's no longer in the config).
    print("Configuring placeholder detector to evict any existing pod for the real detector...")
    glh.configure_edge_endpoint(gl, placeholder_detector)

    # Now configure the real detector. The pod is guaranteed to be freshly
    # created -- there is no carry-over from a prior run.
    glh.configure_edge_endpoint(gl, detector)

    print(
        "\nDetector configuration has been applied. "
        f"Hammering detector for {VICTORY_DURATION_SEC}s with all retries disabled...\n"
    )

    test_start = time.time()
    failures = []
    iteration = 0

    while time.time() - test_start < VICTORY_DURATION_SEC:
        image, _, _ = imgh.generate_random_binary_image()
        try:
            iq = gl.submit_image_query(
                detector=detector,
                image=image,
                **glh.IQ_KWARGS_FOR_NO_ESCALATION,
            )
            print(
                f"[{iteration}] ok | label={iq.result.label.value} | "
                f"confidence={iq.result.confidence:.2f} | from_edge={iq.result.from_edge}"
            )
        except ApiException as e:
            elapsed = time.time() - test_start
            body_preview = str(getattr(e, "body", "") or "")[:300]
            failures.append({
                "iteration": iteration,
                "elapsed_sec": elapsed,
                "status": e.status,
                "body": body_preview,
            })
            print(
                f"[{iteration}] FAIL at t={elapsed:.2f}s | "
                f"status={e.status} | body={body_preview}"
            )
        iteration += 1

    elapsed = time.time() - test_start

    if failures:
        print(
            f"\nBug reproduced: {len(failures)}/{iteration} requests failed "
            f"over {elapsed:.1f}s."
        )
        raise SystemExit(1)

    print(f"\nVictory! {iteration} requests over {elapsed:.1f}s with no errors.")


if __name__ == "__main__":
    main()
