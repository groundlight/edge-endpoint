from groundlight import Groundlight, Detector
import time
import argparse
import os
import subprocess
from threading import Thread

import sys
sys.path.append('../utils')
import utils

TIME_BETWEEN_LABELS = 10.0 # wait time between each label submission, set to something reasonable to avoid overwhelming the system
DETECTOR_CONFIGURATION_INSTRUCTIONS = 'Please configure your detector with an "edge_inference_config" of "no_cloud" in configs/edge-config.yaml.'

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Tests the Edge Endpoint's ability to roll out new inference pods."
    )
    parser.add_argument(
        'detector_id',
        type=str,
        help='Detector ID to use for infernece'
    )
    return parser.parse_args()

def add_label_in_thread(gl: Groundlight, detector: Detector) -> None:
    """
    Submits an image query in a thread with a random image and then labels it.
    """
    def thread() -> None:
        image, label = utils.get_random_binary_image()
        iq = gl.ask_async(detector, image, human_review="NEVER")
        gl.add_label(iq, label)
        print(f'Added {label} label to trigger model training and download.')

    t = Thread(target=thread)
    t.daemon = True
    t.start()

def extract_primary_inference_pods(kubectl_output: str) -> list:
    """
    Extracts all pod names that start with 'inferencemodel-primary'
    AND are in a 'ready' state from the given kubectl get pods output.
    A pod is considered ready if READY is like N/N.
    """
    pods = []
    lines = kubectl_output.strip().splitlines()
    
    # Skip the header (first line)
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue

        pod_name = parts[0]
        ready_field = parts[1]  # e.g. "1/1" or "0/1"

        # Parse readiness: numbers before and after '/'
        try:
            ready, total = map(int, ready_field.split("/"))
        except ValueError:
            continue  # skip if malformed

        if pod_name.startswith("inferencemodel-primary") and ready == total:
            pods.append(pod_name)
    
    return pods

def get_kubernetes_pods_str() -> str:
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", "edge"],
        capture_output=True,
        text=True
    )
    return result.stdout

def main(detector_id: str) -> None:

    endpoint = os.environ.get('GROUNDLIGHT_ENDPOINT')
    if endpoint is None:
        raise ValueError(
            f'GROUNDLIGHT_ENDPOINT was not set in the environment variables. '
            'This test is designed to run against an Edge Endpoint, so this is required. '
            'Set GROUNDLIGHT_ENDPOINT and try again.'
        )

    gl_edge = Groundlight(endpoint=endpoint)

    cloud_endpoint = 'https://api.groundlight.ai/device-api'
    gl_cloud = Groundlight(endpoint=cloud_endpoint) # for submitting labels

    detector = gl_edge.get_detector(detector_id)
    print(f'Retrieved {detector.id}')

    seen_pods = set()

    last_label_submission_time = 0.0
    test_start = time.time()
    while True:

        # try:
        #     kubectl_output = get_kubernetes_pods_str()
        # except KeyboardInterrupt:
        #     break

        # pods = extract_primary_inference_pods(kubectl_output)

        # seen_pods.update(pods)
        # if len(seen_pods) == 0:
        #     raise RuntimeError(
        #         f'No inference pods found for {detector.id}. ' + DETECTOR_CONFIGURATION_INSTRUCTIONS
        #     )

        observed_rollouts = len(seen_pods) - 1

        image, _ = utils.get_random_binary_image()
        
        iq_id = None

        t1 = time.time()
        try:
            iq = gl_edge.submit_image_query(
                detector=detector, 
                image=image, 
                human_review='NEVER', 
                wait=0.0,
                confidence_threshold=1.0 # threshold of 1.0 ensures that the detector is properly configured for edge-only inference
                # could be used for ensuring rapidly inference, but inference times seems to be pretty
                # unstable, even when pods are not rolling out, so this parameter can be problematic for this test
                # request_timeout=1/3,
                )
            iq_id = iq.id
        except KeyboardInterrupt:
            print('Keyboard interrupt')
            break
        except Exception as e:
            print(e)
            break
        finally:
            t2 = time.time()
            elapsed_time = t2 - t1
            fps = 1 / elapsed_time

            test_time_so_far = t2 - test_start
            minutes = int(test_time_so_far // 60)
            seconds = int(test_time_so_far % 60)

            print(f'{minutes:02d}:{seconds:02d} processed {iq_id} in {elapsed_time:.2f} seconds ({fps:.2f} FPS). Observed rollouts: {observed_rollouts}')

        if not iq.result.from_edge:
            raise RuntimeError(
                f'Got a cloud answer on {detector.id}/{iq.id}. '
                'This test requires detectors to always return edge answers. ' + DETECTOR_CONFIGURATION_INSTRUCTIONS
            )

        # # Periodically submit a label to keep a constant flow of training and model download 
        # now = time.time()
        # if now - last_label_submission_time > TIME_BETWEEN_LABELS:
        #     last_label_submission_time = now
        #     add_label_in_thread(gl_cloud, detector)

    test_end = time.time()
    test_elapsed_time = test_end - test_start
    print('-' * 50)
    print(f'Test finished in {test_elapsed_time:.2f} seconds.')

    # Show the current status of pods
    kubectl_output = get_kubernetes_pods_str()
    print(kubectl_output)

if __name__ == "__main__":
    args = parse_arguments()    
    main(args.detector_id)
