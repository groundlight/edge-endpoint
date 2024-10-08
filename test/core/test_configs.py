import pytest
from pydantic import ValidationError

from app.core.configs import DetectorConfig


def test_detector_config():
    try:
        DetectorConfig(
            detector_id="det_xyz",
            local_inference_template="default",
            motion_detection_template="default",
            edge_only=True,
            edge_only_inference=True,
        )
    except Exception as e:
        print(f"Caught exception: {type(e).__name__}")
        print(f"Exception message: {str(e)}")
        raise

    pytest.fail("Expected ValidationError was not raised")
