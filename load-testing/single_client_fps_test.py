from groundlight import ExperimentalApi
from datetime import datetime, timezone
import time
import argparse
from tqdm import tqdm
import statistics

import groundlight_helpers as glh
import image_helpers as imgh

SUPPORTED_DETECTOR_MODES = {
    'BINARY',
    'COUNT',
}
DETECTOR_GROUP_NAME = "Load Testing"

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Groundlight load testing script for a single detector'
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
    TRAINING_TIMEOUT_SEC = 60 * 20
    INFERENCE_POD_READY_TIMEOUT_SEC = 60 * 10

    WARMUP_ITERATIONS = 300
    TESTING_ITERATIONS = 1000
    MIN_PROJECTED_ML_ACCURACY = 0.6
    MIN_TOTAL_LABELS = 30

    # Connect to the GROUNDLIGHT_ENDPOINT defined in the env vars. Should be an edge endpoint.
    gl = ExperimentalApi() 
    glh.error_if_endpoint_is_cloud(gl)
    endpoint = gl.endpoint

    # Connect to a Groundlight cloud endpoint, for certain operations that require the cloud (like adding a label)
    gl_cloud = ExperimentalApi(endpoint=glh.CLOUD_ENDPOINT)

    detector_name = f'Single Client FPS Test {image_width} x {image_height} - {detector_mode}'
    if detector_mode == "BINARY":
        detector = gl.get_or_create_detector(
            name=detector_name,
            query='Is the image background black?',
            group_name=DETECTOR_GROUP_NAME
        )
        generate_image = imgh.generate_random_binary_image
        generate_image_kwargs = {
            "gl": gl,
            "image_width": image_width,
            "image_height": image_height,
        }
    elif detector_mode == "COUNT":
        class_name = "circle"
        max_count = 10
        detector = glh.get_or_create_count_detector(
            gl,
            name=detector_name,
            class_name=class_name,
            max_count=max_count,
            group_name=DETECTOR_GROUP_NAME
        )
        generate_image = imgh.generate_random_count_image
        generate_image_kwargs = {
            "gl": gl,
            "image_width": image_width,
            "image_height": image_height,
            "class_name": class_name,
            "max_count": max_count,
        }
    else:
        raise ValueError(f'Detector mode {detector_mode} not recognized.')

    # Get the pipeline config and log it
    pipeline_configs = glh.get_detector_pipeline_configs(gl, detector.id)
    cloud_pipeline_config = pipeline_configs.get('pipeline_config')
    print(f"Found cloud_pipeline_config='{cloud_pipeline_config}' as the most recently trained pipeline in the cloud. We will use this for testing.")
    
    # Check if the detector has trained. If not, prime it with some labels
    stats = glh.get_detector_stats(gl, detector.id)
    sufficiently_trained = glh.detector_is_sufficiently_trained(stats, MIN_PROJECTED_ML_ACCURACY, MIN_TOTAL_LABELS)
    if sufficiently_trained:
        print(f'{detector.id} is sufficiently trained. Evaluation results: {stats}')
    else:
        print(f'{detector.id} is not yet sufficiently trained. Evaluation results: {stats}')
        glh.prime_detector(gl_cloud, detector, MIN_TOTAL_LABELS, image_width, image_height)

        # After priming, wait until it trains to a sufficient level
        print(f'Waiting up to {TRAINING_TIMEOUT_SEC} seconds for training to complete...')
        stats = glh.wait_until_sufficiently_trained(
            gl,
            detector,
            min_projected_ml_accuracy=MIN_PROJECTED_ML_ACCURACY,
            min_total_labels=MIN_TOTAL_LABELS,
            timeout_sec=TRAINING_TIMEOUT_SEC,
        )
        print(f'{detector.id} is now sufficiently trained. Evaluation results: {stats}')

    # Wait for the inference pod to become available
    print(f"Waiting up to {INFERENCE_POD_READY_TIMEOUT_SEC} seconds for inference pod to be ready for {detector.id} with pipeline_config='{cloud_pipeline_config}'...")
    glh.wait_for_ready_inference_pod(gl, detector, image_width, image_height, cloud_pipeline_config, timeout_sec=INFERENCE_POD_READY_TIMEOUT_SEC)
    edge_pipeline_config = glh.get_detector_edge_metrics(gl, detector.id).get('pipeline_config')
    print(f"Inference pod is ready for {detector.id} with pipeline_config='{edge_pipeline_config}'")

    # Warm up
    for _ in tqdm(range(WARMUP_ITERATIONS), "Warming up"):
        image, _, _ = generate_image(**generate_image_kwargs)
        iq = gl.submit_image_query(detector, image, **glh.IQ_KWARGS_FOR_NO_ESCALATION)
        glh.error_if_not_from_edge(iq)

    # Test
    fps_list = []
    for _ in tqdm(range(TESTING_ITERATIONS), "Running test"):
        image, _, _ = generate_image(**generate_image_kwargs)

        t1 = time.time()
        iq = gl.submit_image_query(detector, image, **glh.IQ_KWARGS_FOR_NO_ESCALATION)
        t2 = time.time()

        glh.error_if_not_from_edge(iq)

        elapsed_time = t2 - t1
        fps = 1 / elapsed_time
        fps_list.append(fps)

    average_fps = sum(fps_list) / len(fps_list)
    min_fps = min(fps_list)
    max_fps = max(fps_list)
    fps_std_dev = statistics.stdev(fps_list)
    fps_p50 = statistics.median(fps_list)
    fps_p10 = statistics.quantiles(fps_list, n=10)[0]  # 1st element (0-indexed) of 10 quantiles = 10th percentile

    # Check if the pipeline running on the edge changed during the test. This seems extremely unlikely, but 
    # it would invalidate the test.
    edge_pipeline_config_end = glh.get_detector_edge_metrics(gl, detector.id).get('pipeline_config')
    if edge_pipeline_config != edge_pipeline_config_end:
        raise RuntimeError(
            f'The pipeline configuration on the Edge Endpoint changed from `{edge_pipeline_config}` to `{edge_pipeline_config_end}`. This test is invalid.'
        )

    # Check which images were used for the `edge-endpoint` container and the inference server container
    edge_image, inference_image = glh.get_edge_and_inference_images(gl)

    test_timestamp = datetime.now(timezone.utc).isoformat()

    # Report results
    print('-' * 10, 'Test Results', '-' * 10)
    print(f'test_timestamp: {test_timestamp}')
    print(f"edge_endpoint_image: {edge_image}")
    print(f"inference_server_image: {inference_image}")
    print(f'detector_id: {detector.id}')
    print(f'pipeline_config: {edge_pipeline_config}')
    print(f'detector_name: {detector.name}')
    print(f'detector_query: {detector.query}')
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
