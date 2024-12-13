import os
import time

import pytest
import requests
from fastapi import status
from groundlight import ApiException, Groundlight
from model import Detector
from PIL import Image

from app.core.utils import pil_image_to_bytes

# Tests in this file require a live edge-endpoint server and GL Api token in order to run.
# Not ideal for unit-testing.
TEST_ENDPOINT = os.getenv("LIVE_TEST_ENDPOINT", "http://localhost:30101")
MAX_WAIT_TIME_S = 60

# Detector ID associated with the detector with parameters
# - name="edge_testing_det",
# - query="Is there a dog in the image?",
# - confidence_threshold=0.9

# we use a dynamically created detector for integration tests
DETECTOR_ID = os.getenv("DETECTOR_ID", "det_2SagpFUrs83cbMZsap5hZzRjZw4")


@pytest.mark.live
@pytest.fixture(scope="module", autouse=True)
def ensure_edge_endpoint_is_live_and_ready():
    """Ensure that the edge-endpoint server is live and ready before running tests."""
    start_time = time.time()
    final_exception = None
    while time.time() - start_time < MAX_WAIT_TIME_S:
        try:
            live_response = requests.get(TEST_ENDPOINT + "/health/live")
            live_response.raise_for_status()
            ready_response = requests.get(TEST_ENDPOINT + "/health/ready")
            ready_response.raise_for_status()
            if live_response.json().get("status") == "alive" and ready_response.json().get("status") == "ready":
                return
        except requests.RequestException as e:
            final_exception = e
            time.sleep(1)  # wait for 1 second before retrying
    pytest.fail(f"Edge endpoint is not live and ready after polling for {MAX_WAIT_TIME_S} seconds. {final_exception=}")


@pytest.fixture(name="gl")
def fixture_gl() -> Groundlight:
    """Create a Groundlight client object."""
    return Groundlight(endpoint=TEST_ENDPOINT)


@pytest.fixture
def detector(gl: Groundlight) -> Detector:
    """Retrieve the detector using the Groundlight client."""
    return gl.get_detector(id=DETECTOR_ID)


@pytest.mark.live
def test_post_image_query_via_sdk(gl: Groundlight, detector: Detector):
    """Test that submitting an image query using the edge server proceeds without failure."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    iq = gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0)
    assert iq is not None, "ImageQuery should not be None."


@pytest.mark.live
def test_post_image_query_via_sdk_want_async(gl: Groundlight, detector: Detector):
    """Test that submitting an image query with want_async=True forwards directly to the cloud."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    iq = gl.ask_async(detector=detector.id, image=image_bytes)
    assert iq is not None, "ImageQuery should not be None."
    assert iq.id.startswith("iq_"), "ImageQuery id should start with 'iq_' because it was created on the cloud."
    assert iq.result is None, "Result should be None because the query is still being processed."


@pytest.mark.live
def test_post_image_query_via_sdk_with_metadata_throws_400(gl: Groundlight, detector: Detector):
    """Test that submitting an image query with metadata raises a 400 error."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    with pytest.raises(ApiException) as exc_info:
        gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0, metadata={"foo": "bar"})
    assert exc_info.value.status == status.HTTP_400_BAD_REQUEST
