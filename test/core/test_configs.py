import pytest

from app.core.configs import DetectorConfig


def test_detector_config_both_edge_modes():
    with pytest.raises(ValueError):
        DetectorConfig(
            detector_id="det_xyz",
            local_inference_template="default",
            motion_detection_template="default",
            edge_only=True,
            edge_only_inference=True,
        )