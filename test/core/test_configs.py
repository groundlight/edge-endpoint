import pytest
from pydantic import ValidationError

from app.core.configs import DetectorConfig


def test_detector_config():
    with pytest.raises(ValidationError):
        DetectorConfig(
            detector_id="det_xyz",
            local_inference_template="default",
            motion_detection_template="default",
            edge_only=True,
            edge_only_inference=True,
        )
