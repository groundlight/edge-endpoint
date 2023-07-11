import pytest
from PIL import Image, ImageFilter
from app.main import app
from app.core.utils import get_motion_detector_instance, get_groundlight_instance
from fastapi.testclient import TestClient
from app.api.api import IMAGE_QUERIES, DETECTORS
from app.api.naming import full_path
from io import BytesIO
import base64
import urllib


client = TestClient(app)


@pytest.fixture
def groundlight():
    return get_groundlight_instance


@pytest.fixture
def motion_detector():
    return get_motion_detector_instance


@pytest.fixture
def detector_id(groundlight):
    detector = groundlight.get_or_create_detector(
        name="edge-testing-dog-detector", query="Is there a dog in the image?", confidence_threshold=0.9
    )
    return detector.id


@pytest.fixture
def detector_id():
    response = client.post(
        full_path(DETECTORS),
        json={
            "name": "edge-testing-detector",
            "query": "Is there a dog in the image?",
            "confidence_threshold": 0.9,
        },
    ).json()

    return response["id"]


def test_motion_detection_blur(detector_id):
    """
    Test motion detection by applying a Gaussian noiser on the query image.
    Every time we submit a new image query, it gets cached in the global motion
    detector state. This test relies on this information to simulate a simple
    test by applying a Gaussian blur on the query image.
    The radius of the blur dictates how much noise will be applied (i.e., the
    standard deviation of the Gaussian distribution).
    Using a Gaussian filter here is not strictly necessary.
    """

    def get_url(image: str) -> str:
        byte_array = BytesIO()
        image.save(byte_array, format="JPEG")
        image_encoding = base64.b64encode(byte_array.getvalue()).decode()
        image_encoding = urllib.parse.quote_plus(image_encoding)

        return full_path(IMAGE_QUERIES) + f"?detector_id={detector_id}&image={image_encoding}&wait=10"

    original_image = Image.open("test/assets/dog.jpeg")

    # Send the POST request without a body
    url = get_url(original_image)
    response = client.post(url).json()
    previous_image_query_id = response["id"]

    blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=50))
    url = get_url(blurred_image)
    response = client.post(url).json()
    new_image_query_id = response["id"]

    assert new_image_query_id != previous_image_query_id, "Motion detected on blurred image"

    previous_image_query_id = new_image_query_id

    # Try to simulate no motion detected
    new_blurred_image = blurred_image.filter(ImageFilter.GaussianBlur(radius=1))
    url = get_url(new_blurred_image)
    response = client.post(url).json()
    new_image_query_id = response["id"]

    assert new_image_query_id == previous_image_query_id, "No motion detected on blurred image"
