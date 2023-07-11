import pytest
import numpy as np
from PIL import Image, ImageFilter
from app.core.motion_detection import AsyncMotionDetector, MotdetParameterSettings
from app.main import app
from app.core.utils import get_motion_detector_instance, get_groundlight_instance
from fastapi.testclient import TestClient
from app.api.api import IMAGE_QUERIES, DETECTORS
from app.api.naming import full_path
from io import BytesIO


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
def detector_created():
    client.post(
        full_path(DETECTORS),
        json={
            "name": "edge-testing-dog-detector",
            "query": "Is there a dog in the image?",
            "confidence_threshold": 0.9,
        },
    )


def test_motion_detection_blur(detector_created):
    original_image = Image.open("test/assets/dog.jpeg")
    url = full_path(IMAGE_QUERIES)

    byte_array = BytesIO()
    original_image.save(byte_array, format="JPEG")

    response = client.post(url, json={"image": byte_array.getvalue(), "detector_id": detector_id, "wait": 10})
    json_response = response.json()

    print(f"json_response: {json_response}")


#     # Convert the image to numpy array
#     original_image_np = np.array(original_image)

#     for i in range(10):  # Adjust the range based on how many iterations you want
#         # Each time, create a new image by blurring the original more
#         blurred_image = original_image.filter(ImageFilter.BLUR)
#         for _ in range(i):
#             blurred_image = blurred_image.filter(ImageFilter.BLUR)

#         # Convert the blurred image to numpy array
#         blurred_image_np = np.array(blurred_image)

#         # Call the motion detector and assert that it detects motion
#         assert await motion_detector.motion_detected(blurred_image_np)

#         # Set the "blurred" image as the new "original" for the next iteration
#         original_image = blurred_image
#         original_image_np = blurred_image_np


# @pytest.mark.asyncio
# async def test_post_image_query_motion_detected(mock_motion_detector_instance, mocker):
#     mock_image_query_create = mocker.MagicMock(spec=ImageQueryCreate)
#     mock_groundlight_instance = mocker.MagicMock(spec=get_groundlight_instance)
#     mock_groundlight_instance.submit_image_query.return_value = "test image query"
#     mock_motion_detector_instance.detect_motion.return_value = True  # mock motion detected
#     mocker.patch("your_app.router.get_motion_detector_instance", return_value=mock_motion_detector_instance)
#     mocker.patch("your_app.router.get_groundlight_instance", return_value=mock_groundlight_instance)
#     response = client.post("", json={"image": "image_data", "detector_id": "detector_id", "wait": 10})
#     assert response.status_code == 200
#     assert response.json() == "test image query"  # adjust this to match the actual expected response
