import logging

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

logger = logging.getLogger(__name__)


class GlobalConfig(BaseModel):
    refresh_rate: float = Field(
        default=60.0,
        description="The interval (in seconds) at which the inference server checks for a new model binary update.",
    )
    confident_audit_rate: float = Field(
        default=0.01,
        description="The rate at which confident predictions are audited.",
    )


class EdgeInferenceConfig(BaseModel):
    """
    Configuration for edge inference on a specific detector.
    """

    enabled: bool = Field(  # TODO investigate and update the functionality of this option
        default=True, description="Whether the edge endpoint should accept image queries for this detector."
    )
    api_token: str | None = Field(
        default=None, description="API token used to fetch the inference model for this detector."
    )
    always_return_edge_prediction: bool = Field(
        default=False,
        description=(
            "Indicates if the edge-endpoint should always provide edge ML predictions, regardless of confidence. "
            "When this setting is true, whether or not the edge-endpoint should escalate low-confidence predictions "
            "to the cloud is determined by `disable_cloud_escalation`."
        ),
    )
    disable_cloud_escalation: bool = Field(
        default=False,
        description=(
            "Never escalate ImageQueries from the edge-endpoint to the cloud."
            "Requires `always_return_edge_prediction=True`."
        ),
    )
    min_time_between_escalations: float = Field(
        default=2.0,
        description=(
            "The minimum time (in seconds) to wait between cloud escalations for a given detector. "
            "Cannot be less than 0.0. "
            "Only applies when `always_return_edge_prediction=True` and `disable_cloud_escalation=False`."
        ),
    )

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if self.disable_cloud_escalation and not self.always_return_edge_prediction:
            raise ValueError(
                "The `disable_cloud_escalation` flag is only valid when `always_return_edge_prediction` is set to True."
            )
        if self.min_time_between_escalations < 0.0:
            raise ValueError("`min_time_between_escalations` cannot be less than 0.0.")
        return self


class DetectorConfig(BaseModel):
    """
    Configuration for a specific detector.
    """

    detector_id: str = Field(..., description="Detector ID")
    edge_inference_config: str = Field(..., description="Config for edge inference.")


class RootEdgeConfig(BaseModel):
    """
    Root configuration for edge inference.
    """

    global_config: GlobalConfig
    edge_inference_configs: dict[str, EdgeInferenceConfig]
    detectors: dict[str, DetectorConfig]

    @model_validator(mode="after")
    def validate_inference_configs(self):
        """
        Validate the edge inference configs specified for the detectors. Example model structure:
            {
                'global_config': {
                    'refresh_rate': 60.0,
                    'confident_audit_rate': 0.01,
                },
                'edge_inference_configs': {
                    'default': EdgeInferenceConfig(
                                    enabled=True,
                                    api_token=None,
                                    always_return_edge_prediction=False,
                                    disable_cloud_escalation=False,
                                    min_time_between_escalations=2.0
                                )
                },
                'detectors': {
                    'detector_1': DetectorConfig(
                                    detector_id='det_123',
                                    edge_inference_config='default'
                                )
                }
            }
        """
        for detector_config in self.detectors.values():
            if detector_config.edge_inference_config not in self.edge_inference_configs:
                raise ValueError(f"Edge inference config {detector_config.edge_inference_config} not defined.")
        return self
