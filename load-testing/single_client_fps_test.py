from groundlight import Groundlight
import os
import time
import argparse
from tqdm import tqdm
import statistics

import utils as u

SUPPORTED_DETECTOR_MODES = {
    'BINARY',
    'COUNT',
}

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Groundlight load testing script with configurable number of detectors'
    )
    parser.add_argument(
        'detector_mode',
        choices=SUPPORTED_DETECTOR_MODES,
        help=f'Detector mode'
    )

    parser.add_argument(
        '--image-width',
        type=int,
        default=640,
    )

    parser.add_argument(
        '--image-height',
        type=int,
        default=480,
    )

    return parser.parse_args()

def main(detector_mode: str, image_width: int, image_height: int) -> None:
    WARMUP_ITERATIONS = 200
    TESTING_ITERATIONS = 100
    MIN_PROJECTED_ML_ACCURACY = 0.6
    MIN_TOTAL_LABELS = 20
    # MIN_CONFIDENCE = 0.6

    endpoint = os.environ.get('GROUNDLIGHT_ENDPOINT')
    if endpoint is None:
        raise ValueError(
            'Please set GROUNDLIGHT_ENDPOINT in your environment variables.'
        ) 

    gl = Groundlight(endpoint=endpoint)
    cloud_endpoint = 'https://api.groundlight.ai/device-api'
    gl_cloud = Groundlight(endpoint=cloud_endpoint)

    detector_name = f'Single Client FPS Test {image_width} x {image_height} - {detector_mode}'
    if detector_mode == "BINARY":
        detector = gl.get_or_create_detector(
            name=detector_name,
            query='Is the image background black?'
        )
        generate_image = u.generate_random_binary_image
        generate_image_kwargs = {
            "gl": gl,
            "image_width": image_width,
            "image_height": image_height,
        }
    elif detector_mode == "COUNT":
        class_name = "circle"
        max_count = 10
        detector = u.get_or_create_count_detector(
            gl,
            name=detector_name,
            class_name=class_name,
            max_count=max_count,
            group_name="Load Testing"
        )
        generate_image = u.generate_random_count_image
        generate_image_kwargs = {
            "gl": gl,
            "image_width": image_width,
            "image_height": image_height,
            "class_name": class_name,
            "max_count": max_count,
        }
    else:
        raise ValueError(f'Detector mode {detector_mode} not recognized.')

    # Check if the detector has trained. If not, prime it with some labels
    stats = u.get_detector_stats(gl, detector.id)
    sufficiently_trained = u.detector_is_sufficiently_trained(stats, MIN_PROJECTED_ML_ACCURACY, MIN_TOTAL_LABELS)
    if sufficiently_trained:
        print(f'{detector.id} is sufficiently trained. Stats: {stats}')
    else:
        print(f'{detector.id} is not sufficiently trained: Stats: {stats}')
        print('Priming detector...')
        u.prime_detector(gl_cloud, detector, MIN_TOTAL_LABELS, image_width, image_height)

        # After priming, wait until it trains to a sufficient level
        print(f'Waiting for {detector.id} to finish training...')
        timeout_sec = 60 * 5
        poll_start = time.time()
        while True:
            stats = u.get_detector_stats(gl, detector.id)
            sufficiently_trained = u.detector_is_sufficiently_trained(stats, MIN_PROJECTED_ML_ACCURACY, MIN_TOTAL_LABELS)
            if sufficiently_trained:
                print(f'{detector.id} is sufficiently trained.')
                break

            elapsed_time = time.time() - poll_start
            if elapsed_time > timeout_sec:
                raise RuntimeError(
                    f'{detector.id} failed to trained sufficiently after {timeout_sec} seconds. Stats: {stats}'
                )
            time.sleep(5)

    # Warm up
    iq_submission_kwargs = {'wait': 0.0, 'human_review': 'NEVER'}
    for _ in tqdm(range(WARMUP_ITERATIONS), "Warming up"):
        image, _, _ = generate_image(**generate_image_kwargs)
        iq = gl.submit_image_query(detector, image, **iq_submission_kwargs)
        u.error_if_not_from_edge(iq)

    # Test
    fps_list = []
    for _ in tqdm(range(TESTING_ITERATIONS), "Running test"):
        image, _, _ = generate_image(**generate_image_kwargs)

        t1 = time.time()
        iq = gl.submit_image_query(detector, image, **iq_submission_kwargs)
        t2 = time.time()

        u.error_if_not_from_edge(iq)

        # Counting mode confidence callibration is off, so this check always fails
        # if iq.result.confidence < MIN_CONFIDENCE:
        #     raise RuntimeError(
        #         f'Got a below confidence answer for {detector.id}. '
        #         f'Confidence: {iq.result.confidence:.3f} < MIN_CONFIDENCE ({MIN_CONFIDENCE}). '
        #     )

        elapsed_time = t2 - t1
        fps = 1 / elapsed_time
        fps_list.append(fps)

    average_fps = sum(fps_list) / len(fps_list)
    min_fps = min(fps_list)
    max_fps = max(fps_list)
    fps_std_dev = statistics.stdev(fps_list)
    fps_p50 = statistics.median(fps_list)
    fps_p10 = statistics.quantiles(fps_list, n=10)[0]  # 1st element (0-indexed) of 10 quantiles = 10th percentile

    # Report results
    print('-' * 10, 'Test Results', '-' * 10)
    print(f'detector_id: {detector.id}')
    print(f'detector_mode: {detector_mode}')
    print(f'image_size: {image_width}x{image_height}')
    print(f'endpoint: {endpoint}')
    print(f'warmup_iterations: {WARMUP_ITERATIONS}')
    print(f'testing_iterations: {TESTING_ITERATIONS}')
    print(f'average_fps: {average_fps:.2f}')
    print(f'min_fps: {min_fps:.2f}')
    print(f'max_fps: {max_fps:.2f}')
    print(f'fps_std_dev: {fps_std_dev:.2f}')
    print(f'fps_p50: {fps_p50:.2f}')
    print(f'fps_p10: {fps_p10:.2f}')

if __name__ == "__main__":
    args = parse_arguments()
    main(args.detector_mode, args.image_width, args.image_height)
