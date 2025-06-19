import argparse
import groundlight
from groundlight import ImageQuery, Label, Groundlight, NotFoundError, ROI
import os 

from threading import Thread

import utils as u

SUPPORTED_MODES = (
    'BINARY',
    'COUNT',
)

# The number of image queries that this script will attempt to submit to the Edge Endpoint, per detector
LOAD_GENERATION_ITERATIONS = 10_000

GROUP_NAME = 'Load Testing'

print(f'Groundlight Version: {groundlight.__version__}')

gl = groundlight.ExperimentalApi()
print(f'Logged in as {gl.whoami()}')

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
    
def add_label_async(
    gl: Groundlight, 
    image_query: ImageQuery | str, 
    label: Label | int | str, 
    rois: list[ROI] = None) -> None:
    """
    Add a label in a separate thread to improve performance.
    Currently only supports binary detectors.
    """
    def thread():
        gl.add_label(image_query, label, rois)
    Thread(target=thread, daemon=True).start()

def main_binary(num_detectors: int) -> None:
    """
    Generate load for a Binary detector
    """
    # Create the detectors
    print(f'Creating {num_detectors} binary detectors for load testing...')
    detectors = []
    for n in range(num_detectors):
        detector_name = f"Black Image Detector (Load Testing) - {n}"
        
        delete_detector_if_exists(detector_name)
            
        new_detector = gl.create_detector(
            detector_name,
            "Is the image background black?",
            group_name=GROUP_NAME,
        )
        print(f'Detector {new_detector.id} created.')
        
        detectors.append(new_detector)

    # Send load to the detectors to trigger inference pod creation
    for i in range(LOAD_GENERATION_ITERATIONS):
        print('-' * 20, f'Iteration {i}', '-' * 20)
        for d in detectors:
            image, label = u.get_random_binary_image()
            
            print('-' * 5, f'Submitting image query to {d.id}...')
            try:
                iq = gl.submit_image_query(
                    detector=d,
                    image=image,
                    wait=0.0,
                    human_review="NEVER",
                )
                print(f'Submitted {iq.id} to {d.id}. from_edge={iq.result.from_edge}')
            except Exception as e:
                print(f'Encountered error while attempting to submit image query: {e}')

            if not iq.result.from_edge:
                add_label_async(gl, iq, label)
                print(f'Added {label} label to {iq.id} on {d.id}.')
                
def main_count(num_detectors: int) -> None:
    """
    Generate load for a Count detector
    """
    # Create the detectors
    print(f'Creating {num_detectors} count detectors for load testing...')
    detectors = []
    for n in range(num_detectors):
        class_name = "circle"
        detector_name = f'Circle Counter - {n}'
        query_text = "Count all the circles"
        max_count = 10
        
        delete_detector_if_exists(detector_name)
        
        detector = gl.create_counting_detector(
            detector_name, 
            query_text, 
            class_name, 
            max_count=max_count,
            group_name=GROUP_NAME,
            )
            
        print(f'Detector {detector.id} created.')
        
        detectors.append(detector)
        
    # Send load to the detectors to trigger inference pod creation
    for i in range(LOAD_GENERATION_ITERATIONS):
        print('-' * 20, f'Iteration {i}', '-' * 20)
        for d in detectors:
            image, rois = u.generate_random_count_image(
                class_name=class_name,
                max_count=max_count,
                image_width=640,
                image_height=480,
            )
            
            print('-' * 5, f'Submitting image query to {d.id}...')
            try:
                confidence_threshold=0.75
                iq = gl.submit_image_query(
                    detector=d,
                    image=image,
                    wait=0.0,
                    human_review="NEVER",
                    confidence_threshold=confidence_threshold
                )
                print(
                    f"Submitted {iq.id} to {d.id}. "
                    f"confidence={iq.result.confidence:.2f} (threshold={confidence_threshold:.2f}) | from_edge={iq.result.from_edge}"
                    )
            except Exception as e:
                print(f'Encountered error while attempting to submit image query: {e}')
                continue # We couldn't submit the image query, so no need to submit a label

            if not iq.result.from_edge:
                add_label_async(gl, iq, len(rois), rois)
                print(f'Added {len(rois)} ROIs to {iq.id} on {d.id}.')

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