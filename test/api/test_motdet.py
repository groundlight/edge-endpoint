import time

import pytest
from groundlight import Groundlight
from PIL import Image, ImageFilter

from app.core.utils import load_edge_config

DETECTORS = {
    "det_2SagpFUrs83cbMZsap5hZzRjZw4": {
        "name": "edge_testing_det",
        "query": "Is there a dog in the image?",
        "confidence_threshold": 0.9,
    }
}


@pytest.fixture(scope="session", autouse=True)
def motion_detection_config():
    """
    Load up detector IDs from the edge config file prior to running any tests.
    """
    config = load_edge_config()
    return config


def motion_detection_enabled(motion_detection_config: dict) -> bool:
    if motion_detection_config is None:
        return False
    configured_detector_ids = [
        detector_params["detector_id"] for detector_params in motion_detection_config["motion_detection"]
    ]
    return all(id_ in configured_detector_ids for id_ in DETECTORS.keys())


@pytest.fixture(name="gl")
def fixture_gl() -> Groundlight:
    """Creates a Groundlight client object"""
    return Groundlight(endpoint="http://localhost:6717")


def test_motion_detection(gl: Groundlight, motion_detection_config: dict):
    """
    Test motion detection by applying a Gaussian noiser on the query image.
    Every time we submit a new image query, it gets cached in the global motion
    detector state. This test relies on this information to simulate a simple
    test by applying a Gaussian blur on the query image.
    The radius of the blur dictates how much noise will be applied (i.e., the
    standard deviation of the Gaussian distribution).
    Using a Gaussian filter here is not strictly necessary.
    """
    if not motion_detection_enabled(motion_detection_config):
        pytest.skip("Motion detection is disabled")

    detector_id = list(DETECTORS.keys())[0]
    detector = gl.get_detector(id=detector_id)

    original_image = Image.open("test/assets/dog.jpeg")

    base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

    for _ in range(5):
        previous_response = base_iq_response
        blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=50))
        new_response = gl.submit_image_query(detector=detector.id, image=blurred_image, wait=10)

        assert new_response.id != previous_response.id and new_response.id.startswith("iq_")

        # Since we don't update the state of the motion detector global object until after we
        # receive a new image that shows motion, this new call to submit_image_query essentially
        # restores the cached image query response to `base_iq_response`. This is guaranteed because
        # we expect that submitting the original image again should indicate that motion was detected again.
        previous_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

        # Simulate no motion detected
        less_blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=0.5))

        new_response = gl.submit_image_query(detector=detector.id, image=less_blurred_image, wait=10)

        assert new_response.id != previous_response.id and new_response.id.startswith("iqe_")


def test_answer_changes_with_different_image(gl: Groundlight, motion_detection_config: dict):
    """
    Tests that the answer changes when we submit a different image while running motion detection.
    """

    if not motion_detection_enabled(motion_detection_config):
        pytest.skip("Motion detection is disabled")

    detector_id = list(DETECTORS.keys())[0]
    detector = gl.get_detector(id=detector_id)

    ITERATIONS = 3
    image = Image.open("test/assets/dog.jpeg")
    image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)

    for _ in range(ITERATIONS):
        image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
        assert image_query.id.startswith("iqe_")

    new_image = Image.open("test/assets/cat.jpeg")
    new_image_query = gl.submit_image_query(detector=detector.id, image=new_image, wait=10)
    assert new_image_query.id.startswith("iq_")


def test_no_motion_detected_response_is_fast(gl: Groundlight, motion_detection_config: dict):
    """
    This test ensures that when no motion is detected the image query response is returned
    extremely fast. This is expected since no API call is made to the server code.

    """

    if not motion_detection_enabled(motion_detection_config):
        pytest.skip("Motion detection is disabled")

    detector_id = list(DETECTORS.keys())[0]
    detector = gl.get_detector(id=detector_id)

    NO_MOTION_DETECTED_RESPONSE_TIME = 0.05

    image = Image.open("test/assets/dog.jpeg")
    start_time = time.time()
    gl.submit_image_query(detector=detector.id, image=image, wait=10)
    total_time_with_motion_detected = time.time() - start_time

    start_time = time.time()
    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
    time.time() - start_time

    # Check that motion was not flagged
    assert new_image_query.id.startswith("iqe_")

    # Check that the time taken to return an image query with no motion detected is much faster
    # than the time taken to return an image query with motion detected.
    assert total_time_with_motion_detected > NO_MOTION_DETECTED_RESPONSE_TIME


def test_max_time_between_cloud_submitted_images(gl: Groundlight, motion_detection_config: dict):
    if not motion_detection_enabled(motion_detection_config):
        pytest.skip("Motion detection is disabled")

    detector_id = list(DETECTORS.keys())[0]
    detector = gl.get_detector(id=detector_id)

    MAX_TIME_BETWEEN_CLOUD_SUBMITTED_IMAGES = 30

    image = Image.open("test/assets/dog.jpeg")
    gl.submit_image_query(detector=detector.id, image=image, wait=10)

    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
    # No motion should be flagged this time since we are submitting the exact same image
    assert new_image_query.id.startswith("iqe_")

    time.sleep(MAX_TIME_BETWEEN_CLOUD_SUBMITTED_IMAGES + 5)

    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
    # No motion should be detected here, but we should still submit the image query to the cloud server
    # since the maximum time between two image query submission to the cloud server has been exceeded.
    assert new_image_query.id.startswith("iq_")
