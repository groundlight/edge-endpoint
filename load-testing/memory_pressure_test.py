import argparse
import groundlight
from groundlight import ImageQuery, Label, Groundlight, NotFoundError, ROI, ApiException, Detector
import os
import uuid
import time
from typing import Callable

from threading import Thread

import utils as u

SUPPORTED_DETECTOR_MODES = (
    'BINARY',
    'COUNT',
)

# The number of image queries that this script will attempt to submit to the Edge Endpoint, per detector
# This is an arbitrarily high number. In practice the script can be stopped once memory usage stabilizes
LOAD_GENERATION_ITERATIONS = 10_000

# Detector group name
GROUP_NAME = 'Load Testing'

def create_client() -> Groundlight:
    # Require the user to explictly set the GROUNDLIGHT_ENDPOINT so that we don't accidentally test
    # against the cloud service.
    endpoint = os.environ.get('GROUNDLIGHT_ENDPOINT')
    if endpoint is None:
        raise ValueError(
            'No GROUNDLIGHT_ENDPOINT has been set. Please set GROUNDLIGHT_ENDPOINT to your edge endpoint URL.'
        )

    timeout_sec = 600
    start_time = time.time()
    e = None
    while True:
        try:
            gl = groundlight.ExperimentalApi(endpoint=endpoint)
            username = gl.whoami()
            print('-' * 20, 'Welcome to Groundlight', '-' * 20)
            print(f'Logged in as {username}')
            print(f'Groundlight SDK Version: {groundlight.__version__}')
            print(f'Groundlight endpoint: {endpoint}')
            return gl
        except Exception as e:
            now = time.time()
            elapsed_time = now - start_time
            if elapsed_time > timeout_sec:
                raise RuntimeError(
                    f'Unable to connect to Groundlight within timeout of {timeout_sec} seconds: {e}'
                )
            print(f'Failed to connect to Groundlight after {int(elapsed_time)} seconds: {type(e).__name__}. Retrying...')
            time.sleep(1)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Groundlight load testing script with configurable number of detectors'
    )
    parser.add_argument(
        'num_detectors',
        type=int,
        help='Number of detectors to create for load testing'
    )
    parser.add_argument(
        'detector_mode',
        choices=SUPPORTED_DETECTOR_MODES,
        help=f'Detector mode'
    )

    parser.add_argument(
        '--confidence-threshold',
        type=float,
        default=0.0,
        help="Confidence threshold for inference. Defaults to 0.0, because this script isn't designed to test ML performance."
    )

    return parser.parse_args()
    
def add_label_async(
    gl: Groundlight, 
    image_query: ImageQuery | str, 
    label: Label | int | str, 
    rois: list[ROI] = None) -> None:
    """
    Add a label in a separate thread to improve performance.
    """
    def thread():
        gl.add_label(image_query, label, rois)
    Thread(target=thread, daemon=True).start()
    
def pprint_iq(iq: ImageQuery, confidence_threshold: float) -> None:
    """
    Pretty print representation of an ImageQuery
    """
    print(
        f"{iq.detector_id}/{iq.id}: "
        f"confidence={iq.result.confidence:.2f} (threshold={confidence_threshold:.2f}) | from_edge={iq.result.from_edge}"
    )

def get_or_create_binary_detectors(
    gl: Groundlight,
    num_detectors: int
) -> list[Detector]:
    detectors = []
    for n in range(num_detectors):
        detector_name = f"Black Image Detector (Load Testing) - {n}"
        
        query = "Is the image background black?"
        detector = gl.get_or_create_detector(
            name=detector_name,
            query=query,
            group_name=GROUP_NAME,
        )
        print(f"{n + 1}: Got or created {detector.id}")
        detectors.append(detector)
    return detectors

def get_or_create_count_detectors(
    gl: Groundlight,
    num_detectors: int,
    class_name: str,
    max_count: int
) -> list[Detector]:
    """
    Create (or fetch if already exists) `num_detectors` count detectors and return them.

    Each detector will have a consistent query based on the provided class_name and max_count.
    """
    detectors: list[Detector] = []

    query_text = f"Count all the {class_name}s"

    for n in range(num_detectors):
        detector_name = f"{class_name.title()} Counter - {n}"
        print(f"{n + 1}:", end=" ", flush=True)
        try:
            detector = gl.create_counting_detector(
                detector_name,
                query_text,
                class_name,
                max_count=max_count,
                group_name=GROUP_NAME,
            )
            print(f"Created {detector.id}")
        except ApiException as e:
            if e.status != 400 or "unique_undeleted_name_per_set" not in getattr(e, "body", ""):
                raise
            detector = gl.get_detector_by_name(detector_name)
            print(f"Retrieved {detector.id}")

        detectors.append(detector)

    return detectors


def set_detector_confidence_threshold(gl: Groundlight, detector: Detector, confidence_threshold: float) -> None:
    """
    Set the confidence threshold for a detector.
    """
    gl.update_detector_confidence_threshold(detector, confidence_threshold)
    detector.confidence_threshold = confidence_threshold

def set_detectors_confidence_threshold(gl: Groundlight, detectors: list[Detector], confidence_threshold: float) -> None:
    """
    Set the confidence threshold for a list of detectors.
    """
    for detector in detectors:
        set_detector_confidence_threshold(gl, detector, confidence_threshold)
        print(f'Adjusted {detector.id} confidence threshold to {confidence_threshold}')
                
def main(num_detectors: int, get_or_create_detectors: Callable, generate_random_image: Callable, kwargs) -> None:
    """
    Generate load for a Count detector
    """
    gl = create_client()

    # Start a timer to measure how long it takes for all edge inference pods to come online
    test_start = time.time()

    # create the detectors and adjust confidence thresholds
    detectors = get_or_create_detectors(gl, num_detectors, **kwargs)
    set_detectors_confidence_threshold(gl, detectors, args.confidence_threshold)
        
    # Send load to the detectors to trigger inference pod creation
    for i in range(LOAD_GENERATION_ITERATIONS):
        num_edge_infereces = 0
        print('-' * 20, f'Iteration {i}', '-' * 20)
        for n, d in enumerate(detectors):
            image_width = 640
            image_height = 480
            image, label, rois = generate_random_image(
                gl=gl,
                image_width=image_width,
                image_height=image_height,
                **kwargs,
            )
            print(f'{n}:', end=' ', flush=True)
            try:
                t1 = time.time()
                iq = gl.submit_image_query(
                    detector=d,
                    image=image,
                    wait=0.0,
                    human_review="NEVER",
                )
                t2 = time.time()
                elapsed_time = t2 - t1
                print(f'({elapsed_time:.2f} sec)', end=' ')
                pprint_iq(iq, d.confidence_threshold)
            except Exception as e:
                print(f'Encountered error while attempting to submit image query: {type(e).__name__}')
                time.sleep(1)
                continue # We couldn't submit the image query, so no need to submit a label

            # Add labels to trigger training and new inference pod rollouts
            # This can be a little problematic if labels are submitted too quickly. Label submission triggers
            # the system to constantly retrain and download new models. When a new model becomes available, it will 
            # interrupt any in-progress download, which might prevent the pod from ever getting a new model.
            # TODO: the Edge endpoint should be updated to always finish its current download before starting a new one.
            if not iq.result.from_edge and iq.result.confidence < d.confidence_threshold:
                add_label_async(gl, iq, label, rois)
                print(f'    --added label {label} to {iq.id} on {d.id}.')

            # Track the number of edge inference pods that have come online
            num_edge_infereces += iq.result.from_edge
            
            # Stop when all pods are online. Record how long it took for all pods to come online.
            if num_edge_infereces == num_detectors:
                test_end = time.time()
                test_duration = test_end - test_start
                print(
                    f'All {num_detectors} edge inference pods came online in no longer than {int(test_duration // 60)} minutes and {test_duration % 60:.2f} seconds ({test_duration:.2f} total seconds).'
                    )
                exit()

if __name__ == "__main__":
    args = parse_arguments()
    
    if args.detector_mode == "BINARY":
        kwargs = {}
        main(
            args.num_detectors, 
            get_or_create_binary_detectors, 
            u.generate_random_binary_image, 
            kwargs
            )
    elif args.detector_mode == "COUNT":
        kwargs = {
            'class_name': 'circle',
            'max_count': 10,
        }
        main(
            args.num_detectors, 
            get_or_create_count_detectors, 
            u.generate_random_count_image, 
            kwargs
            )
    else:
        raise ValueError(
            f'Unrecognized detector mode: {args.detector_mode}'
        )