import time

import pytest
from typing import Callable 
from functools import wraps
from fastapi.testclient import TestClient
from groundlight import Groundlight
from model import Detector
from PIL import Image, ImageFilter
from app.main import app


client = TestClient(app)


class SkipIfMotionDetectionDisabled:
    """
    Decorator that skips a test if motion detection is disabled.
    For now, motion detection has to be explicitly enabled since it is disabled by default.
    This decorator is useful for tests that rely on motion detection being enabled.
    """
    def __init__(self, reason: str = "Motion detection is disabled"):
        self.reason = reason

    def __call__(self, function: Callable):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if not app.state.motion_detector.is_enabled():
                pytest.skip(reason=self.reason)
            return function(*args, **kwargs)

        return wrapper

# Detector ID associated with the detector with parameters
# name="edge_testing_det",
# query="Is there a dog in the image?",
# confidence_threshold=0.9
DETECTOR_ID = "det_2SagpFUrs83cbMZsap5hZzRjZw4"


@pytest.fixture(name="gl")
def fixture_gl() -> Groundlight:
    """Creates a Groundlight client object"""
    return Groundlight(endpoint="http://localhost:6717")


@pytest.fixture
def detector(gl: Groundlight) -> Detector:
    return gl.get_detector(id=DETECTOR_ID)


@SkipIfMotionDetectionDisabled()
def test_motion_detection(gl: Groundlight, detector: Detector):
    """
    Test motion detection by applying a Gaussian noiser on the query image.
    Every time we submit a new image query, it gets cached in the global motion
    detector state. This test relies on this information to simulate a simple
    test by applying a Gaussian blur on the query image.
    The radius of the blur dictates how much noise will be applied (i.e., the
    standard deviation of the Gaussian distribution).
    Using a Gaussian filter here is not strictly necessary.
    """
    original_image = Image.open("test/assets/dog.jpeg")

    base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

    for _ in range(5):
        previous_response = base_iq_response
        blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=50))
        new_response = gl.submit_image_query(detector=detector.id, image=blurred_image, wait=10)

        # We expect that motion is detected on the blurred image
        assert new_response.id != previous_response.id
        assert new_response.type == previous_response.type
        assert new_response.result_type == previous_response.result_type
        assert new_response.result.confidence is None or new_response.result.confidence != previous_response
        assert new_response.result.label != previous_response.result.label
        assert new_response.detector_id == previous_response.detector_id
        assert new_response.query == previous_response.query

        # Since we don't update the state of the motion detecter global object until after we
        # receive a new image that shows motion, this new call to submit_image_query essentially
        # restores the cached image query response to `base_iq_response`. This is guaranteed because
        # we expect that submitting the original image again should indicate that motion was detected again.
        previous_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

        # Simulate no motion detected
        less_blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=0.5))

        new_response = gl.submit_image_query(detector=detector.id, image=less_blurred_image, wait=10)

        assert new_response.id != previous_response.id
        assert new_response.type == previous_response.type
        assert new_response.result_type == previous_response.result_type
        assert new_response.result.confidence == previous_response.result.confidence
        assert new_response.result.label == previous_response.result.label
        assert new_response.detector_id == previous_response.detector_id
        assert new_response.query == previous_response.query


@SkipIfMotionDetectionDisabled()
def test_answer_changes_with_different_image(gl: Groundlight, detector: Detector):
    """
    Tests that the answer changes when we submit a different image while running motion detection.
    """
    ITERATIONS = 3
    image = Image.open("test/assets/dog.jpeg")
    image_query = gl.submit_image_query(detector=detector.id, image=image, wait=5)

    for _ in range(ITERATIONS):
        image_query = gl.submit_image_query(detector=detector.id, image=image, wait=5)
        assert image_query.id.startswith("iqe_")

    new_image = Image.open("test/assets/cat.jpeg")
    new_image_query = gl.submit_image_query(detector=detector.id, image=new_image, wait=5)
    assert new_image_query.id.startswith("iq_")


@SkipIfMotionDetectionDisabled()
def test_no_motion_detected_response_is_fast(gl: Groundlight, detector: Detector):
    """
    This test ensures that when no motion is detected the image query response is returned
    extremely fast. This is expected since no API call is made to the server code.

    """
    NO_MOTION_DETECTED_RESPONSE_TIME = 0.05

    image = Image.open("test/assets/dog.jpeg")
    start_time = time.time()
    image_query = gl.submit_image_query(detector=detector.id, image=image, wait=5)
    total_time_with_motion_detected = time.time() - start_time

    start_time = time.time()
    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=5)
    total_time_with_no_motion_detected = time.time() - start_time

    # Check that motion was indeed detected
    assert new_image_query.id.startswith("iqe_")

    # Check that the time taken to return an image query with no motion detected is much faster
    # than the time taken to return an image query with motion detected.
    assert total_time_with_motion_detected > NO_MOTION_DETECTED_RESPONSE_TIME


def test_max_time_between_cloud_submitted_images(gl: Groundlight, detector: Detector):
    MAX_TIME_BETWEEN_CLOUD_SUBMITTED_IMAGES = 60

    image = Image.open("test/assets/dog.jpeg")
    image_query = gl.submit_image_query(detector=detector.id, image=image, wait=5)

    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=5)
    # No motion should be flagged this time since we are submitting the exact same image
    assert new_image_query.id.startswith("iqe_")

    time.sleep(MAX_TIME_BETWEEN_CLOUD_SUBMITTED_IMAGES + 10)

    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=5)
    # No motion should be detected here, but we should still submit the image query to the cloud server
    # since the maximum time between two image query submission to the cloud server has been exceeded.
    assert new_image_query.id.startswith("iq_")
