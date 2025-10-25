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
DETECTOR_GROUP_NAME = "Load Testing"

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
    TRAINING_TIMEOUT_SEC = 60 * 10
    INFERENCE_POD_READY_TIMEOUT_SEC = 60 * 10

    WARMUP_ITERATIONS = 300
    TESTING_ITERATIONS = 1000
    MIN_PROJECTED_ML_ACCURACY = 0.6
    MIN_TOTAL_LABELS = 30

    # Connect to the GROUNDLIGHT_ENDPOINT defined in the env vars. Should be an edge endpoint.
    gl = Groundlight() 
    u.error_if_endpoint_is_cloud(gl)
    endpoint = gl.endpoint

    # Connect to a Groundlight cloud endpoint, for certain operations that require the cloud (like adding a label)
    gl_cloud = Groundlight(endpoint=u.CLOUD_ENDPOINT)

    detector_name = f'Single Client FPS Test {image_width} x {image_height} - {detector_mode}'
    if detector_mode == "BINARY":
        detector = gl.get_or_create_detector(
            name=detector_name,
            query='Is the image background black?',
            group_name=DETECTOR_GROUP_NAME
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
            group_name=DETECTOR_GROUP_NAME
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

    # Get the pipeline config so that we can log it
    pipeline_config = u.get_detector_pipeline_config(gl, detector.id)
    
    # Check if the detector has trained. If not, prime it with some labels
    stats = u.get_detector_stats(gl, detector.id)
    sufficiently_trained = u.detector_is_sufficiently_trained(stats, MIN_PROJECTED_ML_ACCURACY, MIN_TOTAL_LABELS)
    if sufficiently_trained:
        print(f'{detector.id} is sufficiently trained. Evaluation results: {stats}')
    else:
        print(f'{detector.id} is not yet sufficiently trained. Evaluation results: {stats}')
        u.prime_detector(gl_cloud, detector, MIN_TOTAL_LABELS, image_width, image_height)

        # After priming, wait until it trains to a sufficient level
        print(f'Waiting up to {TRAINING_TIMEOUT_SEC} seconds for training to complete...')
        stats = u.wait_until_sufficiently_trained(
            gl,
            detector,
            min_projected_ml_accuracy=MIN_PROJECTED_ML_ACCURACY,
            min_total_labels=MIN_TOTAL_LABELS,
            timeout_sec=TRAINING_TIMEOUT_SEC,
        )
        print(f'{detector.id} is now sufficiently trained. Evaluation results: {stats}')

    # Wait for the inference pod to become availble
    print(f'Waiting up to {INFERENCE_POD_READY_TIMEOUT_SEC} seconds for inference pod to be ready for {detector.id}...')
    u.wait_for_ready_inference_pod(gl, detector, image_width, image_height, timeout_sec=INFERENCE_POD_READY_TIMEOUT_SEC)
    print(f'Inference pod is ready for {detector.id}.')

    # Warm up
    iq_submission_kwargs = {'wait': 0.0, 'human_review': 'NEVER', 'confidence_threshold': 0.0}
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
    print(f'pipeline_config: {pipeline_config.get('pipeline_config')}')
    print(f'oodd_pipeline_config: {pipeline_config.get('oodd_pipeline_config')}')
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
