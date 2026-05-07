"""
A simple test of the basic functions of the Edge Endpoint, including
both edge inference and operations that need to be rerouted to the cloud, such as adding a label, 
ask_async, etc.

Used for testing robustness to network changes.
"""
import argparse
from groundlight import ExperimentalApi

from groundlight.edge import DEFAULT

import groundlight_helpers as glh
import image_helpers as imgh

IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480
NUM_QUERIES = 10

def main(edge_pipeline_config: str | None = None) -> None:
    requested_edge_pipeline_config = glh.normalize_edge_pipeline_config(edge_pipeline_config)
    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    gl_cloud = ExperimentalApi(endpoint=glh.CLOUD_ENDPOINT_PROD)
    detector = glh.provision_detector(
        gl_cloud, "COUNT", "Simple EE Test",
        IMAGE_WIDTH, IMAGE_HEIGHT,
        group_name="Simple EE Test",
        edge_pipeline_config=requested_edge_pipeline_config,
        training_timeout_sec=60 * 10,
    )

    glh.configure_edge_endpoint(gl, detector, edge_inference_config=DEFAULT)

    print(f'Adding a label to {detector.id}...')
    image, label, rois = imgh.generate_random_image(detector, IMAGE_WIDTH, IMAGE_HEIGHT)
    iq = gl.submit_image_query(detector, image, **glh.IQ_KWARGS_NON_HUMAN_CLOUD_ESCALATION)
    gl.add_label(iq, label, rois)
    print(f'Successfully added a label to {detector.id}.')

    print(f'Submitting {NUM_QUERIES} edge queries...')
    for _ in range(NUM_QUERIES):
        image, label, rois = imgh.generate_random_image(detector, IMAGE_WIDTH, IMAGE_HEIGHT)
        iq = gl.submit_image_query(detector, image, **glh.IQ_KWARGS_FOR_NO_ESCALATION)
        glh.error_if_not_from_edge(iq)
    print(f'Successfully submitted {NUM_QUERIES} edge queries.')

    print('Attempting ask_async (should reroute to cloud)...')
    image, label, rois = imgh.generate_random_image(detector, IMAGE_WIDTH, IMAGE_HEIGHT)
    iq = gl.ask_async(detector, image, human_review="NEVER")
    print(f'Successfully got {iq.id} from ask_async.')

    print("Completed simple Edge Endpoint test successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple Edge Endpoint test.")
    parser.add_argument("--edge-pipeline-config", type=str, default=None, help="Edge pipeline configuration name.")
    args = parser.parse_args()
    main(edge_pipeline_config=args.edge_pipeline_config)


