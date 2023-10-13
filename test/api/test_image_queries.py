import pytest
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
    return Groundlight(endpoint="https://localhost:6717", disable_tls_verification=True)


@pytest.fixture
def detector(gl: Groundlight) -> Detector:
    return gl.get_detector(id=DETECTOR_ID)


def test_post_image_queries(gl: Groundlight, detector: Detector):
    """
    Tests that submitting an image query using the edge server proceeds
    without failure.
    """
    image = Image.open("test/assets/dog.jpeg")
    image_bytes = pil_image_to_bytes(img=image)
    gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0)
