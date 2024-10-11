import pytest

from app.core.configs import DetectorConfig


def test_detector_config_validation():
    DetectorConfig(
        detector_id="det_xyz",
        local_inference_template="default",
        always_return_edge_prediction=False,
        disable_cloud_escalation=False,
    )

    DetectorConfig(
        detector_id="det_xyz",
        local_inference_template="default",
        always_return_edge_prediction=True,
        disable_cloud_escalation=False,
    )

    DetectorConfig(
        detector_id="det_xyz",
        local_inference_template="default",
        always_return_edge_prediction=True,
        disable_cloud_escalation=True,
    )

    with pytest.raises(ValueError):
        DetectorConfig(
            detector_id="det_xyz",
            local_inference_template="default",
            always_return_edge_prediction=False,
            disable_cloud_escalation=True,
        )
