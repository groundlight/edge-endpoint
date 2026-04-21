from groundlight import Groundlight, ExperimentalApi, Detector
import subprocess
import threading
import types
import time

import groundlight_helpers as glh
import image_helpers as imgh

LABEL_INTERVAL_SEC = 30.0
LABELS_PER_BATCH = 3
CONFIDENCE_THRESHOLD = 0.0
VICTORY_DURATION_SEC = 4 * 60
MIN_ROLLOUTS = 2


def disable_transport_retries(gl: ExperimentalApi) -> None:
    """Disable urllib3 transport-level retries."""
    gl.configuration.retries = 0


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
    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    gl_cloud = Groundlight(endpoint=glh.CLOUD_ENDPOINT_PROD)

    # Disable internal retries in the python-sdk so that this test surfaces all errors, even if transient
    disable_transport_retries(gl)
    disable_sdk_retries(gl)

    detector = glh.provision_detector(
        gl, gl_cloud, "BINARY", "Rollout Under Load Test",
        group_name="Edge Endpoint Load Testing",
    )

    glh.configure_edge_endpoint(gl, detector)

    # There is a bug where sometimes inference fails if the inference pod came online very recently. 
    # We'll sleep here a bit so that bug doesn't ruin this test. 
    time.sleep(3)

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
