import pytest

from app.core.configs import EdgeInferenceConfig


def test_edge_inference_config_validation():
    EdgeInferenceConfig(
        enabled=True,
        api_token="test_api_token",
        always_return_edge_prediction=False,
        disable_cloud_escalation=False,
        min_time_between_escalations=2.0,
    )

    EdgeInferenceConfig(
        always_return_edge_prediction=True,
        disable_cloud_escalation=False,
    )

    EdgeInferenceConfig(
        always_return_edge_prediction=True,
        disable_cloud_escalation=True,
    )

    EdgeInferenceConfig(
        enabled=False,
        api_token="test_api_token",
        always_return_edge_prediction=True,
        disable_cloud_escalation=False,
        min_time_between_escalations=10,
    )

    EdgeInferenceConfig(
        enabled=False,
        api_token="test_api_token",
        always_return_edge_prediction=True,
        disable_cloud_escalation=False,
        min_time_between_escalations=0.5,
    )

    EdgeInferenceConfig(
        enabled=True,
        api_token="test_api_token",
        always_return_edge_prediction=True,
        disable_cloud_escalation=True,
        min_time_between_escalations=0.0,
    )

    # disable_cloud_escalation cannot be True if always_return_edge_prediction is False
    with pytest.raises(ValueError):
        EdgeInferenceConfig(
            enabled=True,
            api_token="test_api_token",
            always_return_edge_prediction=False,
            disable_cloud_escalation=True,
            min_time_between_escalations=2.0,
        )

    # min_time_between_escalations cannot be less than 0.0
    with pytest.raises(ValueError):
        EdgeInferenceConfig(
            enabled=True,
            api_token="test_api_token",
            always_return_edge_prediction=False,
            disable_cloud_escalation=True,
            min_time_between_escalations=-0.5,
        )
