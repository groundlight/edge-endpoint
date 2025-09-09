from groundlight import Groundlight
import datetime
import time
from model import Detector
import urllib3.exceptions
import argparse

import utils

DETECTOR_GROUP_NAME = 'Rollout Testing'
LABEL_SUBMISSION_PERIOD_SEC = 3.0
STARTING_LABELS = 15 
SUPPORTED_DETECTOR_MODES = (
    'BINARY',
)

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Tests the Edge Endpoint's ability to roll out new inference pods."
    )
    parser.add_argument(
        'num_detectors',
        type=int,
        help='Number of detectors to create for load testing'
    )
    parser.add_argument(
        '--detector_mode',
        choices=SUPPORTED_DETECTOR_MODES,
        default='BINARY',
        help=f'Detector mode'
    )
    return parser.parse_args()

def add_label(gl: Groundlight, detector: Detector) -> None:
    """
    Submits an image query with a randomly image and then labels it.
    """
    image, label = utils.get_random_binary_image()
    iq = gl.ask_async(detector, image, human_review="NEVER")
    gl.add_label(iq, label)
    print(f'Added {label} label to {detector.id}/{iq.id}')


def prime_detector(gl: Groundlight, detector: Detector, num_labels: int) -> None:
    """
    Submits a handful of labels to a detector so that the cloud can train a model. 
    """
    print(f'Priming detector {detector.id}')
    for _ in range(num_labels):
        add_label(gl, detector)

def main(num_detectors: int) -> None:

    gl = Groundlight(endpoint='http://localhost:30101')

    # Create the detectors
    detectors = []
    datetime_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for n in range(num_detectors):
        detector_name = f'Rollout Test Detector - {datetime_str} - {n}'

        detector = gl.create_binary_detector(
            detector_name, 
            query="Is the image completely black?",
            group_name=DETECTOR_GROUP_NAME,
            )
        print(f'Created {detector.id}')
        detectors.append(detector)
        
    detector_completion_statuses = {detector.id: False for detector in detectors}

    # Prime the detectors
    for detector in detectors:
        prime_detector(gl, detector, STARTING_LABELS)

    # Run inference
    test_start = time.time()
    run = True
    while run:
        print('-' * 50)
        
        # Generate data
        image, _ = utils.get_random_binary_image()

        # Submit image query
        for detector in detectors:
            try:
                iq = gl.submit_image_query(
                    detector=detector, 
                    image=image, 
                    human_review='NEVER', 
                    wait=0.0, 
                    confidence_threshold=0.0
                    )
                print(f'Submitted {iq.id} to {detector.id}. from_edge: {iq.result.from_edge}.')
            except urllib3.exceptions.ReadTimeoutError as e:
                print(f"Timeout while submitting image query: {e}")
                time.sleep(1)

            from_edge = iq.result.from_edge
            if from_edge and not detector_completion_statuses[detector.id]:
                print(f'Received an edge answer for {detector.id}. This means the Edge Endpoint was able to successfully rollout an inference pod for this detector.')
                detector_completion_statuses[detector.id] = True

            all_detectors_complete =  all([status for status in detector_completion_statuses.values()])

            # Check if we are getting edge results
            if all_detectors_complete:
                print(f'Received edge answers for all {len(detectors)} detectors.')
                user_input = input('Keep going? (y/n): ').strip().lower()
                if user_input != 'y':
                    print('Quitting...')
                    run = False
                    break
                else:
                    print('Continuing...')

            # Add a label
            add_label(gl, detector)

            # Sleep
            print(f'Waiting {LABEL_SUBMISSION_PERIOD_SEC} seconds...')
            time.sleep(LABEL_SUBMISSION_PERIOD_SEC)

            # Calculate test duration (so far)
            now = time.time()
            test_duration = now - test_start
            print(f'Test duration so far: {test_duration:.2f} seconds')

    print('Done.')

if __name__ == "__main__":
    args = parse_arguments()    
    main(args.num_detectors)
