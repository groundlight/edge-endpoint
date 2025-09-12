from groundlight import Groundlight, Detector
import time
import argparse
import os
from threading import Thread

import sys
sys.path.append('../utils')
import utils

TIME_BETWEEN_LABELS = 10.0 # wait time between each label submission, set to something reasonable to avoid overwhelming the system

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
        print(f'Added {label} label to {detector.id}/{iq.id}')

    t = Thread(target=thread)
    t.daemon = True
    t.start()

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

    last_label_submission_time = 0.0
    while True:

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
        except Exception as e:
            print(e)
            break
        finally:
            t2 = time.time()
            elapsed_time = t2 - t1
            fps = 1 / elapsed_time

            print(f'Processed {iq_id} in {elapsed_time:.2f} seconds ({fps:.2f} FPS)')

        if not iq.result.from_edge:
            raise RuntimeError(
                f'Got a cloud answer on {detector.id}/{iq.id}. '
                'This test requires detectors to always return edge answers. '
                'Please configure your detector with an "edge_inference_config" of "no_cloud" in configs/edge-config.yaml. '
            )

        # Periodically submit a label to keep a constant flow of training and model download 
        now = time.time()
        if now - last_label_submission_time > TIME_BETWEEN_LABELS:
            last_label_submission_time = now
            add_label_in_thread(gl_cloud, detector)

if __name__ == "__main__":
    args = parse_arguments()    
    main(args.detector_id)
