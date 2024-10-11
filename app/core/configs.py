import logging
from typing import Dict, Optional

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

logger = logging.getLogger(__name__)


class LocalInferenceConfig(BaseModel):
    """
    Configuration for local edge inference on a specific detector.
    """

    enabled: bool = Field(default=False, description="True if edge-inference is enabled for a specific detector.")
    api_token: Optional[str] = Field(
        default=None, description="API token used to fetch the inference model for this detector."
    )
    refresh_rate: float = Field(  # TODO: this field is not used on a per-detector basis, remove it
        default=60,
        description="The interval (in seconds) at which the inference server checks for a new model binary update.",
    )


class DetectorConfig(BaseModel):
    """
    Configuration for a specific detector.
    """

    detector_id: str = Field(..., description="Detector ID")
    local_inference_template: str = Field(..., description="Template for local edge inference.")
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

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if self.disable_cloud_escalation and not self.always_return_edge_prediction:
            raise ValueError(
                "The `disable_cloud_escalation` flag is only valid when `always_return_edge_prediction` is set to True."
            )
        return self


class RootEdgeConfig(BaseModel):
    """
    Root configuration for edge inference.
    """

    local_inference_templates: Dict[str, LocalInferenceConfig]
    detectors: Dict[str, DetectorConfig]

    @model_validator(mode="after")
    def validate_templates(self):
        """
        Validate the templates referenced by the detectors.
        :param values: The values passed to the validator. This is a dictionary of the form:
            {
                'detectors': {
                    'detector_1': DetectorConfig(
                                    detector_id='det_123',
                                    local_inference_template='default',
                                    always_return_edge_prediction=False
                                )
                },
                'local_inference_templates': {
                    'default': LocalInferenceConfig(
                                    enabled=True,
                                    refresh_rate=120.0
                                )
                }
            }
        """
        for detector in self.detectors.values():
            if detector.local_inference_template not in self.local_inference_templates:
                raise ValueError(f"Local Inference Template {detector.local_inference_template} not defined.")
        return self
