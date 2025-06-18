import argparse
import groundlight
from groundlight import ImageQuery, Label, Groundlight, NotFoundError
import numpy as np
import random
import cv2
import os 

from threading import Thread

from datetime import datetime

IMAGE_DIMENSIONS = (480, 640, 3)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

def get_random_image() -> tuple[np.ndarray, str]:
    if random.choice([True, False]):
        image = np.zeros(IMAGE_DIMENSIONS, dtype=np.uint8)  # Black image
        text_color = WHITE
        label = "YES"
    else:
        image = np.full(IMAGE_DIMENSIONS, 255, dtype=np.uint8)  # White image
        text_color = BLACK
        label = "NO"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(image, timestamp, (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, text_color, 2)
    return image, label

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
    return parser.parse_args()

def add_label_async(gl: Groundlight, image_query: ImageQuery | str, label: Label | str) -> None:
    """
    Add a label in a separate thread.
    Currently only supports binary detectors.
    """
    def thread():
        gl.add_label(image_query, label)
    Thread(target=thread, daemon=True).start()

def main():
    # Parse command line arguments
    args = parse_arguments()
    NUM_DETECTORS = args.num_detectors
    
    print(f'Groundlight Version: {groundlight.__version__}')

    endpoint = os.environ.get('GROUNDLIGHT_ENDPOINT')
    if endpoint is None:
        raise ValueError(
            'No GROUNDLIGHT_ENDPOINT has been set. Please set GROUNDLIGHT_ENDPOINT to your edge endpoint URL.'
        )
    else:
        print(f'Using Groundlight endpoint: {endpoint}')

    gl = groundlight.ExperimentalApi()
    print(f'Logged in as {gl.whoami()}')

    # Create the detectors
    print(f'Creating {NUM_DETECTORS} detectors for load testing...')
    detectors = []
    for n in range(NUM_DETECTORS):
        detector_name = f"Black Image Detector (Load Testing) - {n}"
        try:
            d = gl.get_detector_by_name(detector_name)
            print(f'Deleting detector {d.id}...')
            gl.delete_detector(d)
            print(f'Detector {d.id} deleted.')
        except NotFoundError:
            print('No detector found.')
            
        new_detector = gl.create_detector(
            detector_name,
            "Is the image background black?",
            group_name="Load Testing",
        )
        print(f'Detector {new_detector.id} created.')
        
        detectors.append(new_detector)

    # Send load to the detectors to trigger inference pod creation
    for i in range(10000):
        print('-' * 20, f'Iteration {i}', '-' * 20)
        for d in detectors:
            image, label = get_random_image()
            
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

if __name__ == "__main__":
    main()