import argparse
import groundlight
from groundlight import ImageQuery, Label, Groundlight, NotFoundError, ROI, ApiException, Detector
import os
import uuid
import time

from threading import Thread

import utils as u

SUPPORTED_MODES = (
    'BINARY',
    'COUNT',
)

# The number of image queries that this script will attempt to submit to the Edge Endpoint, per detector
# This is an arbitrarily high number. In practice the script can be stopped once memory usage stabilizes
LOAD_GENERATION_ITERATIONS = 10_000

# Detector group name
GROUP_NAME = 'Load Testing'

gl = groundlight.ExperimentalApi()
print(f'Groundlight Version: {groundlight.__version__}')
print(f'Logged in as {gl.whoami()}')

# Require the user to explictly set the GROUNDLIGHT_ENDPOINT so that we don't accidentally test
# against the cloud service.
endpoint = os.environ.get('GROUNDLIGHT_ENDPOINT')
if endpoint is None:
    raise ValueError(
        'No GROUNDLIGHT_ENDPOINT has been set. Please set GROUNDLIGHT_ENDPOINT to your edge endpoint URL.'
    )
else:
    print(f'Using Groundlight endpoint: {endpoint}')

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
        choices=SUPPORTED_MODES,
        help=f'Detector mode'
    )
    return parser.parse_args()

def delete_detector_if_exists(detector_name: str) -> bool:
    """
    Attempts to delete a detector by name, if it exists.
    
    Used for cleaning up detectors from previous runtimes.
    """
    try:
        d = gl.get_detector_by_name(detector_name)
        print(f'Deleting detector {d.id}...')
        gl.delete_detector(d)
        print(f'Detector {d.id} deleted.')
        return True
    except NotFoundError:
        print('No detector found.')
        return False
    
def unique_string() -> str:
    """
    Generates a unique string for giving unique names to detectors.
    """
    return str(uuid.uuid4())[:8]
    
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
    
def get_or_create_count_detector(
    detector_name: str,
    query: str,
    class_name: str,
    max_count: int,
    group_name: str,
    confidence_threshold: float,
    ) -> Detector:
    """
    The Python SDK doesn't currently have a function like this, so we will 
    implement one here.
    """
    try:
        detector = gl.create_counting_detector(
            detector_name, 
            query, 
            class_name, 
            max_count=max_count,
            group_name=group_name,
            confidence_threshold=confidence_threshold,
            )
        print(f'Created {detector.id}')
    except ApiException as e:
        if e.status != 400 or \
            "unique_undeleted_name_per_set" not in e.body:
            raise(e)
        
        detector = gl.get_detector_by_name(detector_name)
        print(f'Retrieved detector {detector.id}')
    
    return detector

def main_binary(num_detectors: int) -> None:
    """
    Generate load for a Binary detector
    """
    # Create the detectors
    print(f'Using {num_detectors} binary detectors for load testing.')
    detectors = []
    for n in range(num_detectors):
        detector_name = f"Black Image Detector (Load Testing) - {n}"
        
        query = "Is the image background black?"
        new_detector = gl.get_or_create_detector(
            name=detector_name,
            query=query,
            group_name=GROUP_NAME,
            confidence_threshold=0.75,
        )
        
        detectors.append(new_detector)

    # Send load to the detectors to trigger inference pod creation
    for i in range(LOAD_GENERATION_ITERATIONS):
        print('-' * 20, f'Iteration {i}', '-' * 20)
        for d in detectors:
            image, label = u.get_random_binary_image()
            
            try:
                iq = gl.submit_image_query(
                    detector=d,
                    image=image,
                    wait=0.0,
                    human_review="NEVER",
                )
                pprint_iq(iq, d.confidence_threshold)
            except Exception as e:
                print(f'Encountered error while attempting to submit image query: {e}')
                time.sleep(1)
                continue # We couldn't submit the image query, so no need to submit a label

            if not iq.result.from_edge:
                add_label_async(gl, iq, label)
                print(f'Added {label} label to {iq.id} on {d.id}.')
                
def main_count(num_detectors: int) -> None:
    """
    Generate load for a Count detector
    """
    # Create the detectors
    detectors = []
    for n in range(num_detectors):
        detector_name = f'Circle Counter - {n}'
        query_text = "Count all the circles"
        class_name = "circle"
        max_count = 10
        detector = get_or_create_count_detector(
                detector_name, 
                query_text, 
                class_name, 
                max_count=max_count,
                group_name=GROUP_NAME,
                confidence_threshold=0.75,
                )

        gl.update_detector_confidence_threshold(detector, 0.0)
        detector.confidence_threshold = 0.0
        
        detectors.append(detector)
        
    # Send load to the detectors to trigger inference pod creation
    for i in range(LOAD_GENERATION_ITERATIONS):
        print('-' * 20, f'Iteration {i}', '-' * 20)
        for n, d in enumerate(detectors):
            image, rois = u.generate_random_count_image(
                class_name=class_name,
                max_count=max_count,
                image_width=640,
                image_height=480,
            )
            
            try:
                t1 = time.time()
                iq = gl.submit_image_query(
                    detector=d,
                    image=image,
                    confidence_threshold=0.0,
                    wait=0.0,
                    human_review="NEVER",
                )
                t2 = time.time()
                elapsed_time = t2 - t1
                print(f'{n}: ({elapsed_time:.2f} sec)', end=' ')
                pprint_iq(iq, d.confidence_threshold)
            except Exception as e:
                print(f'Encountered error while attempting to submit image query: {e}')
                time.sleep(1)
                continue # We couldn't submit the image query, so no need to submit a label
            
            # Add labels to trigger training and new inference pod rollouts
            if not iq.result.from_edge:
                add_label_async(gl, iq, len(rois), rois)
                print(f'    --added {len(rois)} ROIs to {iq.id} on {d.id}.')

if __name__ == "__main__":
    args = parse_arguments()
    
    if args.detector_mode == "BINARY":
        main_binary(args.num_detectors)
    elif args.detector_mode == "COUNT":
        main_count(args.num_detectors)
    else:
        raise ValueError(
            f'Unrecognized detector mode: {args.detector_mode}'
        )