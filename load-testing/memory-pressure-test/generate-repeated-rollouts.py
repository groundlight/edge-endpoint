from groundlight import Groundlight
import datetime
import time
import urllib3.exceptions

import utils

DETECTOR_GROUP_NAME = 'Rollout Testing'
LABEL_SUBMISSION_PERIOD_SEC = 3.0
STARTING_LABELS = 30 

gl = Groundlight(endpoint='http://localhost:30101')

datetime_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
detector_name = f'Rollout Test Detector {datetime_str}'

detector = gl.create_binary_detector(
    detector_name, 
    query="Is the image completely black?",
    group_name=DETECTOR_GROUP_NAME,
    )

print(f'Created {detector.id}')

test_start = time.time()
num_added_labels = 0
while True:
    print('-' * 50)
    
    # Generate data
    image, label = utils.get_random_binary_image()

    # Submit image query
    try:
        iq = gl.submit_image_query(
            detector=detector, 
            image=image, 
            human_review='NEVER', 
            wait=0.0, 
            confidence_threshold=0.0
            )
    except urllib3.exceptions.ReadTimeoutError as e:
        print(f"Timeout while submitting image query: {e}")
        time.sleep(1)

    # Check if we are getting edge results
    if iq.result.from_edge:
        print(f'Received an edge answer. This means the Edge Endpoint was able to successfully rollout an inference pod for {detector.id}')
        user_input = input('Keep going? (y/n): ').strip().lower()
        if user_input != 'y':
            print('Quitting...')
            break
        else:
            print('Continuing...')

    # Add a label
    if not iq.result.from_edge:
        gl.add_label(iq, label)
        num_added_labels += 1
        print(f'Added {label} label to {iq.id}.')

    # Sleep
    if num_added_labels < STARTING_LABELS:
        # Don't wait at all until a minimum number of labels has been submitted (enough to decently train the detector)
        # This ensures that a usable model is trained sooner rather than later
        sleep_time = 0.0 
    else:
        sleep_time = LABEL_SUBMISSION_PERIOD_SEC
    print(f'Submitted {iq.id} to {detector.id}. from_edge: {iq.result.from_edge}. Waiting {sleep_time}...')
    time.sleep(sleep_time)

    # Calculate test duration
    now = time.time()
    test_duration = now - test_start
    print(f'Test duration so far: {test_duration:.2f} seconds')


print('Done.')

