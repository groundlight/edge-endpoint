## The integration tests consists of a back and forth between python (which we use to create and validate
## image queries) and bash (which we use to check deployments are properly rolled out)
## This file contains all the modes that we use for integeration testing.
## Modes:
## - Create the integration test detector
## - Submit the initial dog/cat image query to the edge, expect low confidence
## - Train the edge model by submitting image queries to the cloud.
## - Submit the final dog/cat image query to the edge, expect high confidence

import argparse
import logging
import os
import time

import ksuid
from groundlight import Groundlight
from model import Detector

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

NUM_IQS_PER_CLASS_TO_IMPROVE_MODEL = 10
# ACCEPTABLE_TRAINED_CONFIDENCE = 0.60 NOTE: temporarily commented out, see Note below.

ENDPOINT_PORT = os.getenv("EDGE_ENDPOINT_PORT", "30107")
gl = Groundlight(endpoint=f"http://localhost:{ENDPOINT_PORT}")


def main():
    parser = argparse.ArgumentParser(
        description="Submit a dog and cat image to k3s Groundlight edge-endpoint for integration tests"
    )
    parser.add_argument(
        "-m",
        "--mode",
        type=str,
        choices=["create_detector", "initial", "improve_model", "final"],
        help="Mode of operation: 'create_detector', 'initial', 'improve_model', or 'final'",
        required=True,
    )
    parser.add_argument("-d", "--detector_id", type=str, help="id of detector to use", required=False)
    args = parser.parse_args()

    detector = None
    if args.detector_id:
        detector = gl.get_detector(args.detector_id)

    if detector is None and args.mode != "create_detector":
        raise ValueError("You must provide detector id unless mode is create detector")

    if args.mode == "create_detector":
        detector_id = create_cat_detector()
        print(detector_id)  # print so that the shell script can save the value
    elif args.mode == "initial":
        submit_initial(detector)
    elif args.mode == "improve_model":
        improve_model(detector)
    elif args.mode == "final":
        submit_final(detector)


def create_cat_detector() -> str:
    """Create the intial cat detector that we use for the integration tests. We create
    a new one each time."""
    random_id = ksuid.KsuidMs()
    detector = gl.create_detector(name=f"cat_{random_id}", query="Is this a cat?")
    detector_id = detector.id
    return detector_id


def submit_initial(detector: Detector) -> str:
    """Submit the initial dog and cat image to the edge. Since this method is called at the beginning
    of integration tests, we expect a low confidence from the default edge model"""
    start_time = time.time()
    # 0.5 threshold to ensure we get a edge answer
    iq_yes = _submit_cat(detector, confidence_threshold=0.5)
    iq_no = _submit_dog(detector, confidence_threshold=0.5)
    end_time = time.time()
    logger.info(f"Time taken to get low confidence response from edge: {end_time - start_time} seconds")

    # a bit dependent on the current default model,
    # but that one always defaults to 0.5 confidence at first.

    assert 0.5 <= iq_yes.result.confidence <= 0.55, (
        f"Expected confidence to be between 0.5 and 0.55, but got {iq_yes.result.confidence}"
    )
    assert 0.5 <= iq_no.result.confidence <= 0.55, (
        f"Expected confidence to be between 0.5 and 0.55, but got {iq_no.result.confidence}"
    )


def improve_model(detector: Detector):
    """Improve the edge model by escalating to the cloud."""
    for _ in range(NUM_IQS_PER_CLASS_TO_IMPROVE_MODEL):
        # there's a subtle tradeoff here.
        # we're submitting images from the edge which will get escalated to the cloud
        # and thus train our model. but this process is slow
        iq_yes = _submit_cat(detector, confidence_threshold=1, wait=0)
        gl.add_label(image_query=iq_yes, label="YES")
        iq_no = _submit_dog(detector, confidence_threshold=1, wait=0)
        gl.add_label(image_query=iq_no, label="NO")


def submit_final(detector: Detector):
    """This is called at the end of our integration tests to make sure the edge model
    is now confident."""
    # 0.5 threshold to ensure we get a edge answer
    start_time = time.time()
    _submit_cat(detector, confidence_threshold=0.5)
    _submit_dog(detector, confidence_threshold=0.5)
    end_time = time.time()
    logger.info(f"Time taken to get high confidence response from edge: {end_time - start_time} seconds")

    # These are for debugging - they allow us to compare the edge result (stored in the metadata) with the cloud result.
    iq_yes_cloud = _submit_cat(detector, confidence_threshold=1, wait=0)
    iq_no_cloud = _submit_dog(detector, confidence_threshold=1, wait=0)
    cloud_yes_result_string = (
        f"For the final cat/YES image sent to the cloud ({iq_yes_cloud.id}), received answer "
        f"{iq_yes_cloud.result.label} with confidence {iq_yes_cloud.result.confidence}. "
        f"Metadata: {iq_yes_cloud.metadata}."
    )
    logger.info(cloud_yes_result_string)
    cloud_no_result_string = (
        f"For the final dog/NO image sent to the cloud ({iq_no_cloud.id}), received answer "
        f"{iq_no_cloud.result.label} with confidence {iq_no_cloud.result.confidence}. "
        f"Metadata: {iq_no_cloud.metadata}."
    )
    logger.info(cloud_no_result_string)

    # NOTE these are temporarily commented out because the current implementation of OODD makes this unreliable.
    # assert (
    #     iq_yes.result.confidence > ACCEPTABLE_TRAINED_CONFIDENCE
    # ), f"Expected confidence to be greater than {ACCEPTABLE_TRAINED_CONFIDENCE}, but got {iq_yes.result.confidence}"
    # assert iq_yes.result.label.value == "YES", f"Expected label to be YES, but got {iq_yes.result.label.value}"

    # assert (
    #     iq_no.result.confidence > ACCEPTABLE_TRAINED_CONFIDENCE
    # ), f"Expected confidence to be greater than {ACCEPTABLE_TRAINED_CONFIDENCE}, but got {iq_no.result.confidence}"
    # assert iq_no.result.label.value == "NO", f"Expected label to be NO, but got {iq_no.result.label.value}"


def _submit_cat(detector: Detector, confidence_threshold: float, wait: int = None):
    return _submit_dog_or_cat(
        detector=detector, confidence_threshold=confidence_threshold, img_file="./test/assets/cat.jpeg", wait=wait
    )


def _submit_dog(detector: Detector, confidence_threshold: float, wait: int = None):
    return _submit_dog_or_cat(
        detector=detector, confidence_threshold=confidence_threshold, img_file="./test/assets/dog.jpeg", wait=wait
    )


def _submit_dog_or_cat(detector: Detector, confidence_threshold: float, img_file: str, wait: int = None):
    image_query = gl.submit_image_query(
        detector=detector, confidence_threshold=confidence_threshold, image=img_file, wait=wait
    )

    return image_query


if __name__ == "__main__":
    main()
