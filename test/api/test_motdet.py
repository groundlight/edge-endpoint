import random
import time

import pytest
from groundlight import Groundlight
from PIL import Image, ImageEnhance, ImageFilter

from app.core.app_state import load_edge_config
from app.core.configs import RootEdgeConfig

DETECTORS = {
    "dog_detector": {
        "detector_id": "det_2UOxalD1gegjk4TnyLbtGggiJ8p",
        "query": "Is there a dog in the image?",
        "confidence_threshold": 0.9,
    },
    "cat_detector": {
        "detector_id": "det_2UOxao4HZyB9gv4ZVtwMOvdqgh9",
        "query": "Is there a cat in the image?",
        "confidence_threshold": 0.9,
    },
}


@pytest.fixture(scope="session", autouse=True)
def root_config() -> RootEdgeConfig:
    """
    Load up detector IDs from the edge config file prior to running any tests.
    """
    config = load_edge_config()
    return config


def motion_detection_enabled(config: RootEdgeConfig) -> bool:
    configured_detector_ids = [detector.detector_id for detector in config.detectors]

    testing_detector_ids = [detector["detector_id"] for detector in DETECTORS.values()]
    return all(id_ in configured_detector_ids for id_ in testing_detector_ids)


@pytest.fixture(name="gl")
def fixture_gl() -> Groundlight:
    """Creates a Groundlight client object"""
    return Groundlight(endpoint="http://localhost:6717")


def test_motion_detection(gl: Groundlight, root_config: RootEdgeConfig):
    """
    Test motion detection by applying a Gaussian noiser on the query image.
    Every time we submit a new image query, it gets cached in the global motion
    detector state. This test relies on this information to simulate a simple
    test by applying a Gaussian blur on the query image.
    The radius of the blur dictates how much noise will be applied (i.e., the
    standard deviation of the Gaussian distribution).
    Using a Gaussian filter here is not strictly necessary.
    """
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)

    original_image = Image.open("test/assets/dog.jpeg")

    base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

    for _ in range(5):
        previous_response = base_iq_response
        blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=50))
        new_response = gl.submit_image_query(detector=detector.id, image=blurred_image, wait=10)

        assert new_response.id != previous_response.id and new_response.id.startswith("iq_")

        # Since we don't update the state of the motion detector global object until after we
        # receive a new image that shows motion, this new call to submit_image_query essentially
        # restores the cached image query response to `base_iq_response`. This is guaranteed because
        # we expect that submitting the original image again should indicate that motion was detected again.
        previous_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

        # Simulate no motion detected
        less_blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=0.5))

        new_response = gl.submit_image_query(detector=detector.id, image=less_blurred_image, wait=10)

        assert new_response.id != previous_response.id and new_response.id.startswith("iqe_")


def test_answer_changes_with_different_image(gl: Groundlight, root_config: RootEdgeConfig):
    """
    Tests that the answer changes when we submit a different image while running motion detection.
    """

    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)

    ITERATIONS = 2
    image = Image.open("test/assets/dog.jpeg")
    image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)

    for _ in range(ITERATIONS):
        image_query = gl.submit_image_query(detector=detector.id, image=image, wait=0)
        assert image_query.id.startswith("iqe_")

    new_image = Image.open("test/assets/cat.jpeg")
    new_image_query = gl.submit_image_query(detector=detector.id, image=new_image, wait=10)
    assert new_image_query.id.startswith("iq_")


def test_no_motion_detected_response_is_fast(gl: Groundlight, root_config: RootEdgeConfig):
    """
    This test ensures that when no motion is detected the image query response is returned
    extremely fast. This is expected since no API call is made to the server code.

    """

    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)

    NO_MOTION_DETECTED_RESPONSE_TIME = 0.05

    image = Image.open("test/assets/dog.jpeg")
    start_time = time.time()
    gl.submit_image_query(detector=detector.id, image=image, wait=10)
    total_time_with_motion_detected = time.time() - start_time

    start_time = time.time()
    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
    time.time() - start_time

    # Check that motion was not flagged
    assert new_image_query.id.startswith("iqe_")

    # Check that the time taken to return an image query with no motion detected is much faster
    # than the time taken to return an image query with motion detected.
    assert total_time_with_motion_detected > NO_MOTION_DETECTED_RESPONSE_TIME


def test_max_time_between_cloud_submitted_images(gl: Groundlight, root_config: RootEdgeConfig):
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)

    MAX_TIME_BETWEEN_CLOUD_SUBMITTED_IMAGES = 45

    image = Image.open("test/assets/dog.jpeg")
    gl.submit_image_query(detector=detector.id, image=image, wait=10)

    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
    # No motion should be flagged this time since we are submitting the exact same image
    assert new_image_query.id.startswith("iqe_")

    time.sleep(MAX_TIME_BETWEEN_CLOUD_SUBMITTED_IMAGES + 5)

    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
    # No motion should be detected here, but we should still submit the image query to the cloud server
    # since the maximum time between two image query submission to the cloud server has been exceeded.
    assert new_image_query.id.startswith("iq_")


def test_motion_detection_multiple_detectors(gl: Groundlight, root_config: RootEdgeConfig):
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    dog_detector = gl.get_detector(id=DETECTORS["dog_detector"]["detector_id"])
    cat_detector = gl.get_detector(id=DETECTORS["cat_detector"]["detector_id"])

    dog_image = Image.open("test/assets/dog.jpeg")
    cat_image = Image.open("test/assets/cat.jpeg")

    # Apply random noise to the image
    contrast = ImageEnhance.Contrast(cat_image)
    noisy_cat_image = contrast.enhance(random.uniform(0.5, 1))

    dog_image_query = gl.submit_image_query(detector=dog_detector.id, image=dog_image, wait=10)
    cat_image_query = gl.submit_image_query(detector=cat_detector.id, image=noisy_cat_image, wait=10)

    # Motion detection for the cat detector is set to "super-sensitive". Thus, we expect
    # motion will be detected after applying random noise to the image.
    assert cat_image_query.id.startswith("iq_")

    # Submit another image query for the dog detector and confirm that no motion is detected.
    dog_image_query = gl.submit_image_query(detector=dog_detector.id, image=dog_image, wait=10)
    assert dog_image_query.id.startswith("iqe_")


def test_motion_detection_skipped_when_want_async_is_true(gl: Groundlight, root_config: RootEdgeConfig):
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)

    original_image = Image.open("test/assets/dog.jpeg")

    # Set up opportunity for motion detection
    base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

    # A human review is requested, so we expect that motion detection will be skipped.
    new_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=0, want_async=True)

    assert new_response.id != base_iq_response.id, "ImageQuery id should be different whether or not motion det is run"
    assert new_response.id.startswith(
        "iq_"
    ), "ImageQuery id should start with 'iq_' because it was created on the cloud, want_async=True"


def test_motion_detection_skipped_when_human_review_requested(gl: Groundlight, root_config: RootEdgeConfig):
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)

    original_image = Image.open("test/assets/dog.jpeg")

    # Set up opportunity for motion detection
    base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

    # A human review is requested, so we expect that motion detection will be skipped.
    new_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10, human_review="ALWAYS")

    assert new_response.id != base_iq_response.id, "ImageQuery id should be different whether or not motion det is run"
    assert new_response.id.startswith(
        "iq_"
    ), "ImageQuery id should start with 'iq_' because it was created on the cloud, because Human Review was requested"


def test_motion_detection_not_sufficient_if_doesnt_meet_conf_threshold(gl: Groundlight, root_config: RootEdgeConfig):
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)

    # Set detector confidence threshold to 0.90
    gl.update_detector_confidence_threshold(detector.id, 0.90)

    original_image = Image.open("test/assets/dog.jpeg")

    # Set up opportunity for motion detection
    base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, confidence_threshold=0.5)
    if (
        base_iq_response.result is None
        or base_iq_response.result.confidence is None
        or base_iq_response.result.confidence == 1.0
    ):
        pytest.skip("This test requires that the cached image query response has a confidence < 1.0")

    # Update detector confidence threshold to 0.95
    gl.update_detector_confidence_threshold(detector.id, 0.95)

    new_response = gl.submit_image_query(
        detector=detector.id,
        image=original_image,
        confidence_threshold=base_iq_response.result.confidence + 1e-3,  # Require a higher confidence than before
    )

    assert new_response.id != base_iq_response.id, "ImageQuery id should be different whether or not motion det is run"

    if new_response.result is None or new_response.result.confidence is None or new_response.result.confidence > 0.95:
        # Revert the confidence threshold to 0.90
        gl.update_detector_confidence_threshold(detector.id, 0.90)
        pytest.skip("This test requires that the cached image query response has a confidence < 0.95")

    assert new_response.id.startswith("iq_"), (
        "ImageQuery id should start with 'iq_' because it was created on the cloud, because the cached mot det "
        "response did not meet the confidence threshold"
    )

    # Revert the confidence threshold to 0.90
    gl.update_detector_confidence_threshold(detector.id, 0.90)
