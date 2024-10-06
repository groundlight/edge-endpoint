from io import BytesIO

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from groundlight import ApiException, Groundlight
from model import Detector
from PIL import Image

from app.api.api import IMAGE_QUERIES
from app.api.naming import full_path
from app.core.utils import pil_image_to_bytes

url = full_path(IMAGE_QUERIES)

# Detector ID associated with the detector with parameters
# - name="edge_testing_det",
# - query="Is there a dog in the image?",
# - confidence_threshold=0.9
DETECTOR_ID = "det_2SagpFUrs83cbMZsap5hZzRjZw4"


@pytest.fixture(name="gl")
def fixture_gl() -> Groundlight:
    """Create a Groundlight client object."""
    return Groundlight(endpoint="http://localhost:6717")


@pytest.fixture
def detector(gl: Groundlight) -> Detector:
    """Retrieve the detector using the Groundlight client."""
    return gl.get_detector(id=DETECTOR_ID)


def test_post_image_query_via_sdk(gl: Groundlight, detector: Detector, test_client: TestClient):
    """Test that submitting an image query using the edge server proceeds without failure."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    iq = gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0)
    assert iq is not None, "ImageQuery should not be None."


def test_post_image_query_via_sdk_want_async(gl: Groundlight, detector: Detector, test_client: TestClient):
    """Test that submitting an image query with want_async=True forwards directly to the cloud."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    iq = gl.submit_image_query(detector=detector.id, image=image_bytes, wait=0.0, want_async=True)
    assert iq is not None, "ImageQuery should not be None."
    assert iq.id.startswith("iq_"), "ImageQuery id should start with 'iq_' because it was created on the cloud."
    assert iq.result is None, "Result should be None because the query is still being processed."


def test_post_image_query_via_sdk_with_metadata_throws_400(
    gl: Groundlight, detector: Detector, test_client: TestClient
):
    """Test that submitting an image query with metadata raises a 400 error."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    with pytest.raises(ApiException) as exc_info:
        gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0, metadata={"foo": "bar"})
    assert exc_info.value.status == status.HTTP_400_BAD_REQUEST


def test_post_image_query(test_client: TestClient, detector: Detector):
    """Test that submitting an image query using the edge server proceeds without failure."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    response = test_client.post(
        url,
        headers={"Content-Type": "image/jpeg"},
        data=image_bytes,
        params={"detector_id": detector.id},
    )

    # Assert that the response status code is 200 (OK)
    assert response.status_code == status.HTTP_200_OK, "Expected status code 200 OK"

    # Assert that the response contains the expected fields
    response_data = response.json()
    assert "id" in response_data, "Response should contain an 'id' field"


def test_post_image_query_invalid_content_type(test_client: TestClient, detector: Detector):
    """Test submitting an image query with an invalid content type."""
    response = test_client.post(
        url,
        headers={"Content-Type": "text/plain"},
        data=b"not an image",
        params={"detector_id": detector.id},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {"detail": "Request body must be image bytes"}


def test_post_image_query_invalid_image_data(test_client: TestClient):
    """Test submitting an image query with invalid image data."""
    response = test_client.post(url, headers={"Content-Type": "image/jpeg"}, data=b"not an image")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {"detail": "Invalid input image"}


def test_post_image_query_with_confidence_threshold(test_client: TestClient, detector: Detector):
    """Test submitting an image query with a confidence threshold."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    response = test_client.post(
        url,
        headers={"Content-Type": "image/jpeg"},
        data=image_bytes,
        params={"confidence_threshold": 0.8, "detector_id": detector.id},
    )

    assert response.status_code == status.HTTP_200_OK, "Expected status code 200 OK"
    response_data = response.json()
    assert "id" in response_data, "Response should contain an 'id' field"


def test_post_image_query_with_human_review(test_client: TestClient, detector: Detector):
    """Test submitting an image query with human review set to ALWAYS."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    response = test_client.post(
        url,
        headers={"Content-Type": "image/jpeg"},
        data=image_bytes,
        params={"human_review": "ALWAYS", "detector_id": detector.id},
    )

    assert response.status_code == status.HTTP_200_OK, "Expected status code 200 OK"
    response_data = response.json()
    assert "id" in response_data, "Response should contain an 'id' field"


def test_post_image_query_with_invalid_detector_id(test_client: TestClient, detector: Detector):
    """Test submitting an image query with an invalid detector ID."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    response = test_client.post(
        "/image-queries",
        headers={"Content-Type": "image/jpeg"},
        data=image_bytes,
        params={"detector_id": "invalid_id"},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, "Expected status code 404 Not Found"
    assert response.json() == {"detail": "Not Found"}


def test_post_image_query_with_async_request(test_client: TestClient, detector: Detector):
    """Test submitting an image query with want_async set to true."""
    with open("test/assets/dog.jpeg", "rb") as image_file:
        image_bytes = BytesIO(image_file.read()).getvalue()
    response = test_client.post(
        url,
        headers={"Content-Type": "image/jpeg"},
        data=image_bytes,
        params={"want_async": "true", "detector_id": detector.id},
    )

    assert response.status_code == status.HTTP_200_OK, "Expected status code 200 OK"
    response_data = response.json()
    assert "id" in response_data, "Response should contain an 'id' field"


def test_get_image_query_not_found(test_client: TestClient):
    """Test getting an *edge* image query that does not exist."""
    response = test_client.get(url + "/iqe_123")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "Image query with ID iqe_123 not found"}
