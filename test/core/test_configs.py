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

    DetectorConfig(
        detector_id="det_xyz",
        local_inference_template="default",
        always_return_edge_prediction=True,
        disable_cloud_escalation=False,
        min_time_between_escalations=10,
    )

    DetectorConfig(
        detector_id="det_xyz",
        local_inference_template="default",
        always_return_edge_prediction=True,
        disable_cloud_escalation=False,
        min_time_between_escalations=0.5,
    )

    DetectorConfig(
        detector_id="det_xyz",
        local_inference_template="default",
        always_return_edge_prediction=True,
        disable_cloud_escalation=True,
        min_time_between_escalations=None,
    )

    # disable_cloud_escalation cannot be True if always_return_edge_prediction is False
    with pytest.raises(ValueError):
        DetectorConfig(
            detector_id="det_xyz",
            local_inference_template="default",
            always_return_edge_prediction=False,
            disable_cloud_escalation=True,
        )

    # min_time_between_escalations cannot be set if always_return_edge_prediction is False
    with pytest.raises(ValueError):
        DetectorConfig(
            detector_id="det_xyz",
            local_inference_template="default",
            always_return_edge_prediction=False,
            disable_cloud_escalation=False,
            min_time_between_escalations=10,
        )

    # min_time_between_escalations cannot be set if disable_cloud_escalation is True
    with pytest.raises(ValueError):
        DetectorConfig(
            detector_id="det_xyz",
            local_inference_template="default",
            always_return_edge_prediction=True,
            disable_cloud_escalation=True,
            min_time_between_escalations=10,
        )
