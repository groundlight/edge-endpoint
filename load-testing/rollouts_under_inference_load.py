from groundlight import Groundlight, ExperimentalApi, Detector
from groundlight.edge import EdgeEndpointConfig, NO_CLOUD
import subprocess
import threading
import types
import time
import os

import groundlight_helpers as glh
import image_helpers as imgh

DETECTOR_NAME = 'Rollout Under Load Test'
DETECTOR_GROUP_NAME = 'Edge Endpoint Load Testing'
LABEL_INTERVAL_SEC = 30.0
LABELS_PER_BATCH = 3
MIN_STARTING_LABELS = 30
CONFIDENCE_THRESHOLD = 0.0
VICTORY_DURATION_SEC = 4 * 60
MIN_ROLLOUTS = 2


def disable_sdk_retries(gl: ExperimentalApi) -> None:
    """Monkeypatch the SDK's internal API client to remove the RequestsRetryDecorator
    from call_api, so that 5xx errors propagate immediately without retries.
    NOTE: This reaches into SDK internals and may break if the retry decorator changes."""
    api = gl.api_client
    api.call_api = types.MethodType(api.call_api.__wrapped__, api)


def get_max_inference_revision() -> int:
    """Get the highest revision number across all inferencemodel deployments."""
    result = subprocess.run(
        ["kubectl", "get", "deployments", "-n", "edge",
         "-o", "jsonpath={range .items[*]}{.metadata.name}={.metadata.annotations.deployment\\.kubernetes\\.io/revision}{\"\\n\"}{end}"],
        capture_output=True, text=True,
    )
    max_rev = 0
    for line in result.stdout.strip().splitlines():
        if "=" not in line:
            continue
        name, rev = line.split("=", 1)
        if name.startswith("inferencemodel-"):
            max_rev = max(max_rev, int(rev))
    return max_rev


def _add_label_sync(gl_cloud: Groundlight, detector: Detector) -> None:
    """Submit a random image query via the cloud client and label it."""
    image, label, _ = imgh.generate_random_binary_image(gl_cloud)
    iq = gl_cloud.ask_async(detector, image, human_review="NEVER")
    gl_cloud.add_label(iq, label)

def add_label(gl_cloud: Groundlight, detector: Detector) -> None:
    """Fire-and-forget label submission in a background thread."""
    threading.Thread(target=_add_label_sync, args=(gl_cloud, detector), daemon=True).start()


def main():
    endpoint = os.environ.get('GROUNDLIGHT_ENDPOINT')
    if endpoint is None:
        raise ValueError(
            'GROUNDLIGHT_ENDPOINT must be set. This test must run against an Edge Endpoint.'
        )

    gl = ExperimentalApi(endpoint=endpoint)
    gl_cloud = Groundlight(endpoint="https://api.groundlight.ai")
    # Disable urllib3 transport-level retries
    gl.configuration.retries = 0
    # Disable the SDK's own 5xx retry decorator
    disable_sdk_retries(gl)

    detector = gl.get_or_create_detector(
        DETECTOR_NAME,
        query="Is the image completely black?",
        group_name=DETECTOR_GROUP_NAME,
    )
    print(f'Using detector {detector.id}')

    # Prime the detector if it hasn't been trained yet
    stats = glh.get_detector_evaluation(gl, detector.id)
    if stats['projected_ml_accuracy'] is None:
        num_existing = stats['total_labels'] or 0
        num_needed = max(0, MIN_STARTING_LABELS - num_existing)
        if num_needed > 0:
            print(f'Priming detector with {num_needed} labels...')
            for i in range(num_needed):
                _add_label_sync(gl_cloud, detector)
                print(f'  [{i+1}/{num_needed}] primed')

        print('Waiting for model training...')
        poll_timeout_sec = 120
        start = time.time()
        while True:
            stats = glh.get_detector_evaluation(gl, detector.id)
            if stats['projected_ml_accuracy'] is not None:
                print(f'Training complete. Projected ML accuracy: {stats["projected_ml_accuracy"]:.2f}')
                break
            elapsed = time.time() - start
            if elapsed > poll_timeout_sec:
                raise RuntimeError(f'Model training did not complete within {poll_timeout_sec}s')
            time.sleep(5)
    else:
        print(f'Detector already trained. Projected ML accuracy: {stats["projected_ml_accuracy"]:.2f}')

    # Configure edge with NO_CLOUD
    edge_config = EdgeEndpointConfig()
    edge_config.add_detector(detector, NO_CLOUD)
    print('Pushing edge config (NO_CLOUD)...')
    gl.edge.set_config(edge_config)
    print('Edge config applied, inference pod ready.')

    # Record deployment revision before the test to verify rollouts occurred.
    revision_before = get_max_inference_revision()
    print(f'Max inference deployment revision before test: {revision_before}')

    # Inference loop: submit as fast as possible, with periodic labels to trigger model rollouts.
    last_label_time = 0
    iteration = 0
    test_start = time.time()
    print(f'\nStarting inference loop. Labels submitted every {LABEL_INTERVAL_SEC}s to trigger rollouts.')
    print(f'Will declare victory after {VICTORY_DURATION_SEC}s with no errors.')
    print('All retries disabled -- 503s will propagate immediately.\n')

    while time.time() - test_start < VICTORY_DURATION_SEC:
        image, _, _ = imgh.generate_random_binary_image(gl)
        iq = gl.submit_image_query(
            detector=detector,
            image=image,
            human_review='NEVER',
            wait=0.0,
            confidence_threshold=CONFIDENCE_THRESHOLD,
        )
        print(
            f'[{iteration}] {iq.id} | '
            f'label={iq.result.label.value} | '
            f'confidence={iq.result.confidence:.2f} | '
            f'from_edge={iq.result.from_edge}'
        )

        now = time.time()
        if now - last_label_time >= LABEL_INTERVAL_SEC:
            print(f'  Submitting {LABELS_PER_BATCH} labels to trigger retraining...')
            for _ in range(LABELS_PER_BATCH):
                add_label(gl_cloud, detector)
            last_label_time = now

        iteration += 1

    elapsed = time.time() - test_start

    # Verify that enough rollouts occurred during the test.
    revision_after = get_max_inference_revision()
    rollouts = revision_after - revision_before
    if rollouts < MIN_ROLLOUTS:
        raise RuntimeError(
            f'Only {rollouts} rollout(s) occurred during the test ({iteration} queries over '
            f'{elapsed:.0f}s), need at least {MIN_ROLLOUTS}. Results are inconclusive.'
        )

    print(f'\nVictory! Ran {iteration} inference queries over {elapsed:.0f}s through '
          f'{rollouts} rollout(s) with no errors.')


if __name__ == "__main__":
    main()
