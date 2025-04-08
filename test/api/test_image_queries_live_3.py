import os
import time

import pytest
import requests
from fastapi import status
from groundlight import ApiException, Detector, Groundlight, ImageQuery
from PIL import Image

from app.core.utils import pil_image_to_bytes

# Tests in this file require a live edge-endpoint server and GL Api token in order to run.
# Not ideal for unit-testing.
TEST_ENDPOINT = os.getenv("LIVE_TEST_ENDPOINT", "http://localhost:30101")
MAX_WAIT_TIME_S = 60

# Detectors for live testing. On the prod-biggies account.
# - name="live_edge_testing_1",
# - query="Is there a dog in the image?",
# - confidence_threshold=0.9
DETECTOR_ID_1 = "det_2raefZ74V0ojgbmM2UJzQCpFKyF"
# - name="live_edge_testing_2",
# - query="Is there a dog in the image?",
# - confidence_threshold=0.9
DETECTOR_ID_2 = "det_2rdUY6SJOBJtuW5oqD3ExL1DjFn"
# - name="live_edge_testing_3",
# - query="Is there a dog in the image?",
# - confidence_threshold=0.9
DETECTOR_ID_3 = "det_2rdUb0jljHCosfKGuTugVoo4eiY"
# - name="live_edge_testing_4",
# - query="Is there a dog in the image?",
# - confidence_threshold=0.9
DETECTOR_ID_4 = "det_2rdVBErF53NWjVjhVdIrb6QJbRT"

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#             Fixtures
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


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
def detector_default(gl: Groundlight) -> Detector:
    """Retrieve the default detector using the Groundlight client."""
    return gl.get_detector(id=DETECTOR_ID_1)


@pytest.fixture
def detector_edge_answers(gl: Groundlight) -> Detector:
    """Retrieve the edge answers detector using the Groundlight client."""
    return gl.get_detector(id=DETECTOR_ID_2)


@pytest.fixture
def detector_no_cloud(gl: Groundlight) -> Detector:
    """Retrieve the no cloud detector using the Groundlight client."""
    return gl.get_detector(id=DETECTOR_ID_3)


@pytest.fixture
def detector_disabled(gl: Groundlight) -> Detector:
    """Retrieve the disabled detector using the Groundlight client."""
    return gl.get_detector(id=DETECTOR_ID_4)


@pytest.fixture
def image_bytes() -> bytes:
    """Return the test image as bytes."""
    return pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#             Helpers
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


def answer_is_from_cloud(iq: ImageQuery) -> bool:
    """Return True if the answer is from the cloud, False otherwise."""
    return not iq.metadata or not iq.metadata.get("is_from_edge", False)


def answer_is_from_edge(iq: ImageQuery) -> bool:
    """Return True if the answer is from the edge, False otherwise."""
    return iq.metadata and iq.metadata.get("is_from_edge", False)


def was_escalated(gl: Groundlight, iq: ImageQuery, max_retries: int = 3, retry_delay: float = 1.0) -> bool:
    """Return True if the answer was escalated to the cloud, False otherwise.
    Retries up to max_retries times, waiting retry_delay seconds between retries, to account for the time it takes for
    the cloud to process the image query.

    Args:
        gl: Groundlight client
        iq: ImageQuery to check
        max_retries: Maximum number of retry attempts
        retry_delay: Delay in seconds between retries
    """
    for attempt in range(max_retries):
        try:
            gl.get_image_query(id=iq.id)
            return True
        except ApiException as e:
            if e.status == status.HTTP_404_NOT_FOUND and attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            if e.status == status.HTTP_404_NOT_FOUND:
                return False
            raise


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#             Tests
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


@pytest.mark.live
class TestSubmittingToLocalInferenceConfigs:
    """Tests for submitting image queries with different detector configurations."""

    class TestDefaultConfig:
        """Tests for default detector configuration behavior."""

        def test_high_threshold_goes_to_cloud(self, gl: Groundlight, detector_default: Detector, image_bytes: bytes):
            iq = gl.submit_image_query(
                detector=detector_default.id, image=image_bytes, confidence_threshold=1, wait=0
            )  # TODO is this dependent on getting a fast cloud response?
            assert iq is not None, "ImageQuery should not be None."
            assert answer_is_from_cloud(iq), "Answer should be from the cloud."

        def test_low_threshold_comes_from_edge(self, gl: Groundlight, detector_default: Detector, image_bytes: bytes):
            iq = gl.submit_image_query(
                detector=detector_default.id, image=image_bytes, confidence_threshold=0.5, wait=0
            )
            assert iq is not None, "ImageQuery should not be None."
            assert answer_is_from_edge(iq), "Answer should be from the edge."

    class TestEdgeAnswersConfig:
        """Tests for edge_answers_with_escalation detector configuration."""

        def test_high_threshold_comes_from_edge_and_escalated(
            self, gl: Groundlight, detector_edge_answers: Detector, image_bytes: bytes
        ):
            iq = gl.submit_image_query(
                detector=detector_edge_answers.id, image=image_bytes, confidence_threshold=1, wait=0
            )
            assert iq is not None, "ImageQuery should not be None."
            assert answer_is_from_edge(iq), "Answer should be from the edge."
            assert was_escalated(gl, iq), "Answer should be escalated."

        def test_low_threshold_comes_from_edge(
            self, gl: Groundlight, detector_edge_answers: Detector, image_bytes: bytes
        ):
            iq = gl.submit_image_query(
                detector=detector_edge_answers.id, image=image_bytes, confidence_threshold=0.5, wait=0
            )
            assert iq is not None, "ImageQuery should not be None."
            assert answer_is_from_edge(iq), "Answer should be from the edge."
            assert not was_escalated(gl, iq), "Answer should not be escalated."

    class TestNoCloudConfig:
        """Tests for no_cloud detector configuration."""

        def test_high_threshold_comes_from_edge_not_escalated(self, gl, detector_no_cloud, image_bytes):
            iq = gl.submit_image_query(detector=detector_no_cloud.id, image=image_bytes, confidence_threshold=1, wait=0)
            assert iq is not None, "ImageQuery should not be None."
            assert answer_is_from_edge(iq), "Answer should be from the edge."
            assert not was_escalated(gl, iq), "Answer should not be escalated."

        def test_low_threshold_comes_from_edge(self, gl, detector_no_cloud, image_bytes):
            iq = gl.submit_image_query(
                detector=detector_no_cloud.id, image=image_bytes, confidence_threshold=0.5, wait=0
            )
            assert iq is not None, "ImageQuery should not be None."
            assert answer_is_from_edge(iq), "Answer should be from the edge."
            assert not was_escalated(gl, iq), "Answer should not be escalated."

    class TestDisabledConfig:
        """Tests for disabled detector configuration."""

        def test_low_threshold_goes_to_cloud(self, gl: Groundlight, detector_disabled: Detector, image_bytes: bytes):
            iq = gl.submit_image_query(
                detector=detector_disabled.id, image=image_bytes, confidence_threshold=0.5, wait=0
            )
            assert iq is not None, "ImageQuery should not be None."
            assert answer_is_from_cloud(iq), "Answer should be from the cloud."


@pytest.mark.live
class TestEdgeQueryParams:
    """Testing behavior of submit_image_query parameters on edge."""

    class TestWantAsync:
        """Tests for want_async parameter behavior."""

        @pytest.mark.parametrize("detector_fixture", ["detector_edge_answers", "detector_no_cloud"])
        def test_want_async_not_allowed_with_edge_answers(
            self, gl: Groundlight, request: pytest.FixtureRequest, detector_fixture: str, image_bytes: bytes
        ):
            """Test that want_async cannot be specified when edge answers are required."""
            detector = request.getfixturevalue(detector_fixture)
            with pytest.raises(ApiException) as exc_info:
                gl.submit_image_query(detector=detector.id, image=image_bytes, want_async=True, wait=0)
            assert exc_info.value.status == status.HTTP_400_BAD_REQUEST

        def test_want_async_goes_to_cloud(self, gl: Groundlight, detector_default: Detector, image_bytes: bytes):
            """Test that want_async=True always goes to the cloud."""
            iq = gl.submit_image_query(
                detector=detector_default.id, image=image_bytes, want_async=True, confidence_threshold=0.5, wait=0
            )
            assert iq is not None
            assert answer_is_from_cloud(iq), "Answer should be from the cloud."

        def test_want_async_can_be_submitted_without_error(
            self, gl: Groundlight, detector_default: Detector, image_bytes: bytes
        ):
            """Test that want_async can be submitted without error."""
            iq = gl.submit_image_query(detector=detector_default.id, image=image_bytes, want_async=False, wait=0)
            assert iq is not None

    class TestHumanReview:
        """Tests for human_review parameter behavior."""

        @pytest.mark.parametrize("detector_fixture", ["detector_edge_answers", "detector_no_cloud"])
        def test_human_review_not_allowed_with_edge_answers(
            self, gl: Groundlight, request: pytest.FixtureRequest, detector_fixture: str, image_bytes: bytes
        ):
            """Test that human_review cannot be specified when edge answers are required."""
            detector = request.getfixturevalue(detector_fixture)
            with pytest.raises(ApiException) as exc_info:
                gl.submit_image_query(detector=detector.id, image=image_bytes, human_review="ALWAYS")
            assert exc_info.value.status == status.HTTP_400_BAD_REQUEST

        def test_always_human_review_goes_to_cloud(
            self, gl: Groundlight, detector_default: Detector, image_bytes: bytes
        ):
            """Test that human_review=ALWAYS always goes to the cloud."""
            iq = gl.submit_image_query(
                detector=detector_default.id, image=image_bytes, human_review="ALWAYS", confidence_threshold=0.5, wait=0
            )
            assert iq is not None
            assert answer_is_from_cloud(iq), "Answer should be from the cloud."

        def test_human_review_can_be_submitted_without_error(
            self, gl: Groundlight, detector_default: Detector, image_bytes: bytes
        ):
            """Test that human_review=(NEVER/DEFAULT) can be submitted without error."""
            iq = gl.submit_image_query(detector=detector_default.id, image=image_bytes, human_review="NEVER", wait=0)
            assert iq is not None

            iq = gl.submit_image_query(detector=detector_default.id, image=image_bytes, human_review="DEFAULT", wait=0)
            assert iq is not None

    class TestWait:
        """Tests for wait parameter behavior."""

        # TODO figure out what the functionality should be and test it

        def test_wait_can_be_submitted_without_error(
            self, gl: Groundlight, detector_no_cloud: Detector, image_bytes: bytes
        ):
            """Test that zero and non-zero wait times can be submitted without error."""
            # Wait of 0
            wait_time = 0
            iq = gl.submit_image_query(
                detector=detector_no_cloud.id, image=image_bytes, wait=wait_time, confidence_threshold=1
            )
            assert iq is not None

            # Non-zero wait
            wait_time = 1.5
            start_time = time.time()
            iq = gl.submit_image_query(
                detector=detector_no_cloud.id, image=image_bytes, wait=wait_time, confidence_threshold=1
            )
            elapsed = time.time() - start_time
            assert elapsed >= wait_time, f"Query took {elapsed:.2f}s but should have taken at least {wait_time}s"
            assert iq is not None

    class TestPatienceTime:
        """Tests for patience_time parameter behavior."""

        # TODO figure out what the functionality should be and test it

        def test_patience_time_can_be_submitted_without_error(
            self, gl: Groundlight, detector_no_cloud: Detector, image_bytes: bytes
        ):
            """Test that patience_time can be submitted without error."""
            iq = gl.submit_image_query(detector=detector_no_cloud.id, image=image_bytes, patience_time=1.0)
            assert iq is not None

    class TestConfidenceThreshold:
        """
        Tests for confidence_threshold parameter behavior. This is implicitly tested in other tests, so we just do a
        simple check here.
        """

        def test_confidence_threshold_can_be_submitted_without_error(
            self, gl: Groundlight, detector_no_cloud: Detector, image_bytes: bytes
        ):
            """Test that confidence_threshold can be submitted without error."""
            iq = gl.submit_image_query(detector=detector_no_cloud.id, image=image_bytes, confidence_threshold=0.8)
            assert iq is not None

    @pytest.mark.parametrize(
        "unsupported_param",
        [
            {"inspection_id": "insp_123"},
            {"metadata": {"test": "value"}},
            {"image_query_id": "iq_123"},
        ],
    )
    def test_unsupported_params_raise_error(
        self,
        gl: Groundlight,
        detector_default: Detector,
        image_bytes: bytes,
        unsupported_param: dict,
    ):
        """Test that unsupported parameters raise a 400 error."""
        with pytest.raises(ApiException) as exc_info:
            gl.submit_image_query(detector=detector_default.id, image=image_bytes, **unsupported_param)
        assert exc_info.value.status == status.HTTP_400_BAD_REQUEST


# @pytest.mark.live
# def test_post_image_query_via_sdk(gl: Groundlight, detector: Detector, image_bytes: bytes):
#     """Test that submitting an image query using the edge server proceeds without failure."""
#     iq = gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0)
#     assert iq is not None, "ImageQuery should not be None."


# @pytest.mark.live
# def test_post_image_query_via_sdk_want_async(gl: Groundlight, detector: Detector, image_bytes: bytes):
#     """Test that submitting an image query with want_async=True forwards directly to the cloud."""
#     iq = gl.ask_async(detector=detector.id, image=image_bytes)
#     assert iq is not None, "ImageQuery should not be None."
#     assert iq.id.startswith("iq_"), "ImageQuery id should start with 'iq_' because it was created on the cloud."
#     assert iq.result is None, "Result should be None because the query is still being processed."


# @pytest.mark.live
# def test_post_image_query_via_sdk_with_metadata_throws_400(gl: Groundlight, detector: Detector, image_bytes: bytes):
#     """Test that submitting an image query with metadata raises a 400 error."""
#     with pytest.raises(ApiException) as exc_info:
#         gl.submit_image_query(detector=detector.id, image=image_bytes, wait=10.0, metadata={"foo": "bar"})
#     assert exc_info.value.status == status.HTTP_400_BAD_REQUEST
