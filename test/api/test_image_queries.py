import base64
import urllib.parse
from io import BytesIO

import pytest
from PIL import Image

from app.api.api import DETECTORS, IMAGE_QUERIES
from app.api.naming import full_path
from app.main import app

from ..conftest import TestClient

client = TestClient(app)


@pytest.fixture
def detector_id():
    response = client.post(
        full_path(DETECTORS),
        json={
            "name": "edge_testing",
            "query": "Is there a dog in the image?",
            "confidence_threshold": 0.9,
        },
    ).json()
    assert "id" in response
    return response["id"]


def test_post_image_queries(detector_id):
    """
    NOTE: We need to encode the image as a base64 string since bytes are not
    JSON-serializable.
    """
    image = Image.open("test/assets/dog.jpeg")
    byte_array = BytesIO()
    image.save(byte_array, format="JPEG")

    image_encoding = base64.b64encode(byte_array.getvalue()).decode()
    image_encoding = urllib.parse.quote_plus(image_encoding)

    url = full_path(IMAGE_QUERIES) + f"?detector_id={detector_id}&image={image_encoding}&wait=10"

    response = client.post(url).json()

    assert "id" in response
    assert "detector_id" in response
    assert "query" in response
    assert "created_at" in response
    assert "type" in response
    assert "result" in response
    assert "result_type" in response
    assert response["detector_id"] == detector_id
