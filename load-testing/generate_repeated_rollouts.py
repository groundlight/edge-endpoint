from groundlight import Groundlight, Detector
import time
import urllib3.exceptions
import argparse
import os

import groundlight_helpers as glh
import image_helpers as imgh

DETECTOR_GROUP_NAME = 'Edge Endpoint Rollout Testing'
LABEL_SUBMISSION_WAIT_TIME_SEC = 3.0 # wait time between each label submission, set to something reasonable to avoid overwhelming the system
MIN_STARTING_LABELS = 30 # ensure that each detector has at leat this number of labels before beginning the test
CONFIDENCE_THRESHOLD = 0.1 # use a super low threshold because we don't care about ML accuracy, only want to see that we can get edge answers
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
    Submits an image query with a random image and then labels it.
    """
    image, label, _ = imgh.generate_random_binary_image(gl)
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

    endpoint = os.environ.get('GROUNDLIGHT_ENDPOINT')
    if endpoint is None:
        raise ValueError(
            f'GROUNDLIGHT_ENDPOINT was not set in the environment variables. '
            'This test is designed to run against an Edge Endpoint, so this is required. '
            'Set GROUNDLIGHT_ENDPOINT and try again.'
        )

    gl = Groundlight(endpoint=endpoint)

    # Get or create the detectors
    detectors = []
    for n in range(num_detectors):
        # detector_name = f'Rollout Test Detector - {datetime_str} - {n}'
        detector_name = f'Edge Endpoint Rollout Test Detector - {n}'

        detector = gl.get_or_create_detector(
            detector_name, 
            query="Is the image completely black?",
            group_name=DETECTOR_GROUP_NAME,
            )
        print(f'Got or created {detector.id}')
        detectors.append(detector)
        
    detector_completion_statuses = {detector.id: False for detector in detectors}

    # Prime the detectors, if necessary
    for detector in detectors:
        detector_stats = glh.get_detector_evaluation(gl, detector.id)

        projected_ml_accuracy = detector_stats['projected_ml_accuracy']
        if projected_ml_accuracy is not None:
            print(
                f'{detector.id} has a Projected ML accuracy of {projected_ml_accuracy:.2f} '
                'No need to provide additional training labels.'
            )
            continue
        else:
            print(
                f'{detector.id} has no evaluation results. '
                'We might need to prime the detector.'
            )


        total_labels = detector_stats['total_labels']
        num_labels_to_add = MIN_STARTING_LABELS - total_labels
        if num_labels_to_add > 0:
            print(
                f'{detector.id} only has {total_labels} ground truth labels. '
                f'Needs an additional {num_labels_to_add} labels. Priming detector...'
            )
            prime_detector(gl, detector, num_labels_to_add)
        else:
            print(
                f'{detector.id} already has enough labels (actual={total_labels}, required={MIN_STARTING_LABELS}). No need to prime.'
            )

    # Wait for evaluation to occur
    poll_timeout_sec = 2 * 60 
    for detector in detectors:
        print(f'Checking evaluation results for {detector.id}...')
        pollstart = time.time()
        while True:
            detector_stats = glh.get_detector_evaluation(gl, detector.id)
            projected_ml_accuracy = detector_stats['projected_ml_accuracy']

            if projected_ml_accuracy is not None:
                print(f'Evaluation has completed for {detector.id}. Projected ML Accuracy: {projected_ml_accuracy:.2f}')
                break

            now = time.time()
            elapsed_time = now - pollstart
            if elapsed_time > poll_timeout_sec:
                raise RuntimeError(
                    f'Failed to receive evaluation results for {detector.id} after {elapsed_time} seconds.'
                )

            time.sleep(5)

    # Run inference
    test_start = time.time()
    test_complete = False # once all inference pods are online, we'll call the test done, and allow the user to continue running inference
    run = True
    iteration = 0
    while run:
        print('-' * 50)
        
        # Generate data
        image, _, _ = imgh.generate_random_binary_image(gl)

        # Submit image query
        for detector in detectors:
            try:
                iq = gl.submit_image_query(
                    detector=detector, 
                    image=image, 
                    human_review='NEVER', 
                    wait=0.0, 
                    confidence_threshold=CONFIDENCE_THRESHOLD
                    )
                print(
                    f'Submitted {iq.id} to {detector.id} - label: {iq.result.label.value} | confidence: {iq.result.confidence:.2f} | from_edge: {iq.result.from_edge}'
                    )
            except urllib3.exceptions.ReadTimeoutError as e:
                print(f"Timeout while submitting image query: {e}")
                time.sleep(1)

            from_edge = iq.result.from_edge

            # Check for unexpected cloud escalations
            if not from_edge and iq.metadata.get('edge_result') is not None:
                raise RuntimeError(
                    f"Got a cloud result for {iq.id} even though edge inference occurred. "
                    "It seems the Edge Endpoint escalated to the cloud even though it shouldn't have."
                )

            # Register if we got a cloud response for this detector
            if from_edge and not detector_completion_statuses[detector.id]:
                print(f'Received an edge answer for {detector.id}. This means the Edge Endpoint was able to successfully rollout an inference pod for this detector.')
                detector_completion_statuses[detector.id] = True

            # Check if all detectors are complete (have received edge answers)
            all_detectors_complete =  all([status for status in detector_completion_statuses.values()])

            # Check if the test should conclude
            if not test_complete and all_detectors_complete:
                test_complete = True
                if iteration == 0:
                    print(
                        f'Got edge responses from all {len(detectors)} detectors on first iteration of test. '
                        'This likely means that inference pods were already rolled out prior to starting this test. '
                        'Therefore, this test is likely invalid. Consider redeploying your Edge Endpoint and running the test again.'
                        )
                else:
                    now = time.time()
                    complete_test_duration = now - test_start
                    print(f'Received edge answers for all {len(detectors)} detectors. Test completed in {complete_test_duration:.2f} seconds.')

                user_input = input('Would you like to continue running to trigger more rollouts? (y/n): ').strip().lower()
                if user_input != 'y':
                    print('Quitting...')
                    run = False
                    break
                else:
                    print('Continuing...')

            # Add a label
            add_label(gl, detector)

            # Sleep
            print(f'Waiting {LABEL_SUBMISSION_WAIT_TIME_SEC} seconds...')
            time.sleep(LABEL_SUBMISSION_WAIT_TIME_SEC)

            # Calculate test duration (so far)
            now = time.time()
            test_duration = now - test_start
            print(f'Test duration so far: {test_duration:.2f} seconds')

        iteration += 1

    print('Done.')

if __name__ == "__main__":
    args = parse_arguments()    
    main(args.num_detectors)
