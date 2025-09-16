from groundlight import Groundlight
import time
import argparse
import os

import sys
sys.path.append('../utils')
import utils

DETECTOR_CONFIGURATION_INSTRUCTIONS = 'Please configure your detector with an "edge_inference_config" of "no_cloud" in configs/edge-config.yaml.'
FPS_AVERAGING_WINDOW_LEN = 200

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

def main(detector_id: str) -> None:

    endpoint = os.environ.get('GROUNDLIGHT_ENDPOINT')
    if endpoint is None:
        raise ValueError(
            f'GROUNDLIGHT_ENDPOINT was not set in the environment variables. '
            'This test is designed to run against an Edge Endpoint, so this is required. '
            'Set GROUNDLIGHT_ENDPOINT and try again.'
        )

    gl = Groundlight(endpoint=endpoint)

    detector = gl.get_detector(detector_id)
    print(f'Retrieved {detector.id}')

    fps_values = []

    while True:

        image, _, _ = utils.generate_random_binary_image(gl)
        
        iq_id = None

        t1 = time.time()
        try:
            iq = gl.submit_image_query(
                detector=detector, 
                image=image, 
                human_review='NEVER', 
                wait=0.0,
                confidence_threshold=1.0, # threshold of 1.0 ensures that the detector is properly configured for edge-only inference
                # could be used for ensuring rapidly inference, but inference times seems to be pretty
                # unstable, even when pods are not rolling out, so this parameter can be problematic for this test
                # request_timeout=0.5,
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

            fps_values.append(fps)
            if len(fps_values) > FPS_AVERAGING_WINDOW_LEN:
                del fps_values[0]

            average_fps = sum(fps_values) / len(fps_values)

            print(f'Processed {iq_id} in {elapsed_time:.2f} seconds ({fps:.2f} FPS). Average FPS: {average_fps:.2f}')

        if not iq.result.from_edge:
            raise RuntimeError(
                f'Got a cloud answer on {detector.id}/{iq.id}. '
                'This test requires detectors to always return edge answers. ' + DETECTOR_CONFIGURATION_INSTRUCTIONS
            )

if __name__ == "__main__":
    args = parse_arguments()    
    main(args.detector_id)