"""
A simple of the basic functions of the Edge Endpoint, including
both edge inference and operations that need to be rerouted to the cloud, such as adding a label, 
ask_async, contacting the edge metrics API, etc.

Used for testing robustness to network changes.
"""
from groundlight import ExperimentalApi

import groundlight_helpers as glh
import image_helpers as imgh

DETECTOR_GROUP_NAME = "Simple EE Test"
CLASS_NAME = "circle"
MAX_COUNT = 10
IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480
NUM_QUERIES = 10

MIN_PROJECTED_ML_ACCURACY = 0.0 # we don't really care about accuracy for this test
MIN_TOTAL_LABELS = 30
TRAINING_TIMEOUT_SEC = 10 * 60

INFERENCE_POD_READY_TIMEOUT_SEC = 60 * 10

def main() -> None:
    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)

    detector = glh.get_or_create_count_detector(
        gl,
        name="Simple EE Test - Count",
        class_name=CLASS_NAME,
        max_count=MAX_COUNT,
        group_name=DETECTOR_GROUP_NAME,
    )

    pipeline_configs = glh.get_detector_pipeline_configs(gl, detector.id)
    latest_edge_pipeline_config_in_cloud = pipeline_configs.get('pipeline_config')
    print(f"Found the following pipeline config as the most recently trained Edge pipeline config in the cloud. We will use this for testing: {latest_edge_pipeline_config_in_cloud}")

    # Check if the detector has trained. If not, prime it with some labels
    stats = glh.get_detector_evaluation(gl, detector.id)
    sufficiently_trained = glh.detector_is_sufficiently_trained(stats, MIN_PROJECTED_ML_ACCURACY, MIN_TOTAL_LABELS)
    if sufficiently_trained:
        print(f'{detector.id} is sufficiently trained. Evaluation results: {stats}')
    else:
        print(f'{detector.id} is not yet sufficiently trained. Evaluation results: {stats}')
        glh.prime_detector(gl, detector, MIN_TOTAL_LABELS, IMAGE_WIDTH, IMAGE_HEIGHT)

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
    print(f"Waiting up to {INFERENCE_POD_READY_TIMEOUT_SEC} seconds for inference pod to be ready for {detector.id} with pipeline_config='{latest_edge_pipeline_config_in_cloud}'...")
    glh.wait_for_ready_inference_pod(gl, detector, IMAGE_WIDTH, IMAGE_HEIGHT, latest_edge_pipeline_config_in_cloud, timeout_sec=INFERENCE_POD_READY_TIMEOUT_SEC)
    print('done waiting')
    edge_pipeline_config = glh.get_detector_edge_metrics(gl, detector.id).get('pipeline_config')
    print(f"Inference pod is ready for {detector.id} with pipeline_config='{edge_pipeline_config}'")

    print(f'Adding a label to {detector.id}...')
    image, label, rois = imgh.generate_random_image(gl, detector, IMAGE_WIDTH, IMAGE_HEIGHT)
    iq = gl.submit_image_query(detector, image, **glh.IQ_KWARGS_NON_HUMAN_CLOUD_ESCALATION)
    gl.add_label(iq, label, rois)
    print(f'Successfully added a label to {detector.id}.')

    print(f'Submitting {NUM_QUERIES} edge queries...')
    for _ in range(NUM_QUERIES):
        image, label, rois = imgh.generate_random_image(gl, detector, IMAGE_WIDTH, IMAGE_HEIGHT)
        iq = gl.submit_image_query(detector, image, **glh.IQ_KWARGS_FOR_NO_ESCALATION)
        glh.error_if_not_from_edge(iq)
    print(f'Successfully submitted {NUM_QUERIES} edge queries.')

    print('Attempting ask_async (should reroute to cloud)...')
    image, label, rois = imgh.generate_random_image(gl, detector, IMAGE_WIDTH, IMAGE_HEIGHT)
    iq = gl.ask_async(detector, image, human_review="NEVER")
    print(f'Successfully got {iq.id} from ask_async.')

    print("Completed simple Edge Endpoint test successfully.")

if __name__ == "__main__":
    main()


