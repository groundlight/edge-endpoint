import pytest
from fastapi import status
from groundlight import ApiException, Groundlight
from model import Detector
from PIL import Image

from app.core.utils import pil_image_to_bytes

# Tests in this file require a live edge-endpoint server and GL Api token in order to run.
# Not ideal for unit-testing.


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


def test_post_image_query_via_sdk(gl: Groundlight, detector: Detector):
    """Test that submitting an image query using the edge server proceeds without failure."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    iq = gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0)
    assert iq is not None, "ImageQuery should not be None."


def test_post_image_query_via_sdk_want_async(gl: Groundlight, detector: Detector):
    """Test that submitting an image query with want_async=True forwards directly to the cloud."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    iq = gl.submit_image_query(detector=detector.id, image=image_bytes, wait=0.0, want_async=True)
    assert iq is not None, "ImageQuery should not be None."
    assert iq.id.startswith("iq_"), "ImageQuery id should start with 'iq_' because it was created on the cloud."
    assert iq.result is None, "Result should be None because the query is still being processed."


def test_post_image_query_via_sdk_with_metadata_throws_400(gl: Groundlight, detector: Detector):
    """Test that submitting an image query with metadata raises a 400 error."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    with pytest.raises(ApiException) as exc_info:
        gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0, metadata={"foo": "bar"})
    assert exc_info.value.status == status.HTTP_400_BAD_REQUEST