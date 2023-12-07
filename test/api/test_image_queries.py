import pytest
from fastapi import HTTPException
from groundlight import Groundlight
from model import Detector
from PIL import Image

from app.core.utils import pil_image_to_bytes
from app.main import app

from ..conftest import TestClient

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


def test_post_image_query(gl: Groundlight, detector: Detector):
    """
    Tests that submitting an image query using the edge server proceeds without failure.
    """
    image = Image.open("test/assets/dog.jpeg")
    image_bytes = pil_image_to_bytes(img=image)
    iq = gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0)
    assert iq is not None, "ImageQuery should not be None."


def test_post_image_query_want_async(gl: Groundlight, detector: Detector):
    """
    Tests that submitting an image query using the edge server with want_async=True forwards directly to the cloud.
    """
    image = Image.open("test/assets/dog.jpeg")
    image_bytes = pil_image_to_bytes(img=image)
    iq = gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0, want_async=True)
    assert iq is not None, "ImageQuery should not be None."
    assert iq.id.startswith("iq_"), "ImageQuery id should start with 'iq_' because it was created on the cloud."
    assert iq.result is None, "Result should be None because the query is still being processed."


def test_post_image_query_with_metadata_throws_400(gl: Groundlight, detector: Detector):
    """
    Tests that submitting an image query with metadata using the edge server raises a 400 error.
    """
    image = Image.open("test/assets/dog.jpeg")
    image_bytes = pil_image_to_bytes(img=image)
    with pytest.raises(HTTPException) as exc_info:
        gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0, metadata={"foo": "bar"})
    assert exc_info.value.status_code == 400
