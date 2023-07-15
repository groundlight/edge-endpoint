import base64
import urllib
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageFilter

from app.api.api import DETECTORS, IMAGE_QUERIES
from app.api.naming import full_path
from app.main import app

client = TestClient(app)

# Detector ID associated with the detector with parameters
# name="edge_testing_det",
# query="Is there a dog in the image?",
# confidence_threshold=0.9
DETECTOR_ID = "det_2SagpFUrs83cbMZsap5hZzRjZw4"


@pytest.fixture
def detector_id():
    url = full_path(DETECTORS) + f"/{DETECTOR_ID}"
    response = client.get(url).json()

    return response["id"]


def get_post_image_query_url(detector: str, image: Image.Image, wait: float = 10) -> str:
    """
    Constructs full URL for `submit_image_query` by first converting a PIL image
    into a base64-encoded string.
    """
    byte_array = BytesIO()
    image.save(byte_array, format="JPEG")
    image_encoding = base64.b64encode(byte_array.getvalue()).decode()
    image_encoding = urllib.parse.quote_plus(image_encoding)

    return full_path(IMAGE_QUERIES) + f"?detector_id={detector}&image={image_encoding}&wait={wait}"


def test_motion_detection(detector_id):
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

    url = get_post_image_query_url(detector=detector_id, image=original_image, wait=10)
    base_response = client.post(url).json()

    for _ in range(10):
        previous_response = base_response
        blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=50))
        url = get_post_image_query_url(detector=detector_id, image=blurred_image, wait=10)
        new_response = client.post(url).json()

        # We expect that motion is detected on the blurred image

        assert new_response["id"] != previous_response["id"]
        assert new_response["type"] == previous_response["type"]
        assert new_response["result_type"] == previous_response["result_type"]
        assert (
            new_response["result"]["confidence"] is None
            or new_response["result"]["confidence"] != previous_response["result"]["confidence"]
        )
        assert new_response["result"]["label"] != previous_response["result"]["label"]
        assert new_response["detector_id"] == previous_response["detector_id"]
        assert new_response["query"] == previous_response["query"]
        assert new_response["created_at"] != previous_response["created_at"]

        previous_response = new_response

        # Simulate no motion detected
        new_blurred_image = blurred_image.filter(ImageFilter.GaussianBlur(radius=1))
        url = get_post_image_query_url(detector=detector_id, image=new_blurred_image, wait=10)
        new_response = client.post(url).json()

        assert new_response["id"] != previous_response["id"]
        assert new_response["type"] == previous_response["type"]
        assert new_response["result_type"] == previous_response["result_type"]
        assert new_response["result"]["confidence"] == previous_response["result"]["confidence"]
        assert new_response["result"]["label"] == previous_response["result"]["label"]
        assert new_response["detector_id"] == previous_response["detector_id"]
        assert new_response["query"] == previous_response["query"]
        assert new_response["created_at"] == previous_response["created_at"]
