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
    """Load detector IDs from the edge config file before running tests."""
    return load_edge_config()


def motion_detection_enabled(config: RootEdgeConfig) -> bool:
    configured_detector_ids = config.detectors.keys()
    testing_detector_ids = [detector["detector_id"] for detector in DETECTORS.values()]
    return all(id_ in configured_detector_ids for id_ in testing_detector_ids)


@pytest.fixture(name="gl")
def fixture_gl() -> Groundlight:
    """Create a Groundlight client object."""
    return Groundlight(endpoint="http://localhost:6717")


def test_motion_detection(gl: Groundlight, root_config: RootEdgeConfig):
    """Test motion detection by applying Gaussian noise to the query image."""
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)
    original_image = Image.open("test/assets/dog.jpeg")
    base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

    for _ in range(5):
        blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=50))
        new_response = gl.submit_image_query(detector=detector.id, image=blurred_image, wait=10)
        assert new_response.id != base_iq_response.id and new_response.id.startswith("iq_")

        base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)
        less_blurred_image = original_image.filter(ImageFilter.GaussianBlur(radius=0.5))
        new_response = gl.submit_image_query(detector=detector.id, image=less_blurred_image, wait=10)
        assert new_response.id != base_iq_response.id and new_response.id.startswith("iqe_")


def test_answer_changes_with_different_image(gl: Groundlight, root_config: RootEdgeConfig):
    """Test that the answer changes when submitting a different image."""
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)
    image = Image.open("test/assets/dog.jpeg")
    image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)

    for _ in range(2):
        image_query = gl.submit_image_query(detector=detector.id, image=image, wait=0)
        assert image_query.id.startswith("iqe_")

    new_image = Image.open("test/assets/cat.jpeg")
    new_image_query = gl.submit_image_query(detector=detector.id, image=new_image, wait=10)
    assert new_image_query.id.startswith("iq_")


def test_no_motion_detected_response_is_fast(gl: Groundlight, root_config: RootEdgeConfig):
    """Ensure fast response when no motion is detected."""
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)
    image = Image.open("test/assets/dog.jpeg")
    start_time = time.time()
    gl.submit_image_query(detector=detector.id, image=image, wait=10)
    total_time_with_motion_detected = time.time() - start_time

    start_time = time.time()
    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
    assert new_image_query.id.startswith("iqe_")
    assert total_time_with_motion_detected > 0.05


def test_max_time_between_cloud_submitted_images(gl: Groundlight, root_config: RootEdgeConfig):
    """Test maximum time between cloud-submitted images."""
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)
    image = Image.open("test/assets/dog.jpeg")
    gl.submit_image_query(detector=detector.id, image=image, wait=10)

    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
    assert new_image_query.id.startswith("iqe_")

    time.sleep(50)
    new_image_query = gl.submit_image_query(detector=detector.id, image=image, wait=10)
    assert new_image_query.id.startswith("iq_")


def test_motion_detection_multiple_detectors(gl: Groundlight, root_config: RootEdgeConfig):
    """Test motion detection with multiple detectors."""
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    dog_detector = gl.get_detector(id=DETECTORS["dog_detector"]["detector_id"])
    cat_detector = gl.get_detector(id=DETECTORS["cat_detector"]["detector_id"])
    dog_image = Image.open("test/assets/dog.jpeg")
    cat_image = Image.open("test/assets/cat.jpeg")

    contrast = ImageEnhance.Contrast(cat_image)
    noisy_cat_image = contrast.enhance(random.uniform(0.5, 1))
    cat_image_query = gl.submit_image_query(detector=cat_detector.id, image=noisy_cat_image, wait=10)
    assert cat_image_query.id.startswith("iq_")

    dog_image_query = gl.submit_image_query(detector=dog_detector.id, image=dog_image, wait=10)
    assert dog_image_query.id.startswith("iqe_")


def test_motion_detection_skipped_when_want_async_is_true(gl: Groundlight, root_config: RootEdgeConfig):
    """Test motion detection is skipped when want_async is True."""
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)
    original_image = Image.open("test/assets/dog.jpeg")
    base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

    new_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=0, want_async=True)
    assert new_response.id != base_iq_response.id
    assert new_response.id.startswith("iq_")


def test_motion_detection_skipped_when_human_review_requested(gl: Groundlight, root_config: RootEdgeConfig):
    """Test motion detection is skipped when human review is requested."""
    if not motion_detection_enabled(root_config):
        pytest.skip("Motion detection is disabled")

    detector_id = DETECTORS["dog_detector"]["detector_id"]
    detector = gl.get_detector(id=detector_id)
    original_image = Image.open("test/assets/dog.jpeg")
    base_iq_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10)

    new_response = gl.submit_image_query(detector=detector.id, image=original_image, wait=10, human_review="ALWAYS")
    assert new_response.id != base_iq_response.id
    assert new_response.id.startswith("iq_")
