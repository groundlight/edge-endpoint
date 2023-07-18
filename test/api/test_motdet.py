import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from groundlight import Groundlight
from model import Detector
from PIL import Image, ImageFilter

from app.main import app

client = TestClient(app)

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


def encode_image(image: Image.Image) -> str:
    """
    Returns a base64-encoded string representing the given input image.
    Although the SDK accepts multiple image input types, we encode the image
    as base64 to be consistent with the input type for the edge endpoint.
    (i.e., having a format that is JSON-compatible)
    """
    byte_array = BytesIO()
    image.save(byte_array, format="JPEG")
    image_encoding = base64.b64encode(byte_array.getvalue()).decode()
    # image_encoding = urllib.parse.quote_plus(image_encoding)

    return image_encoding


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

    for _ in range(1):
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
        # assert new_response.created_at != previous_response.created_at

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
