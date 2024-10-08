import logging
from typing import Dict, Optional

from pydantic import BaseModel, Field, model_validator, validator

logger = logging.getLogger(__name__)


class MotionDetectionConfig(BaseModel):
    enabled: bool = Field(..., description="Determines if motion detection is enabled for this detector")
    percentage_threshold: Optional[float] = Field(
        default=None, description="Percent of pixels needed to change before motion is detected."
    )
    val_threshold: Optional[int] = Field(
        default=None, description="The minimum brightness change for a pixel for it to be considered changed."
    )
    max_time_between_images: Optional[float] = Field(
        default=None,
        description=(
            "Specifies the maximum time (seconds) between images sent to the cloud. This will be honored even if no"
            " motion has been detected. Defaults to 1 hour."
        ),
    )
    unconfident_iq_reescalation_interval: float = Field(
        60.0, description="How often to re-escalate unconfident Image queries."
    )


class LocalInferenceConfig(BaseModel):
    """
    Configuration for local edge inference on a specific detector.
    """

    enabled: bool = Field(False, description="Determines if local edge inference is enabled for a specific detector.")
    api_token: Optional[str] = Field(None, description="API token to fetch the inference model for this detector.")
    refresh_rate: float = Field(
        default=120.0,
        description=(
            "The refresh rate for the inference server (in seconds). This means how often to check for an updated model"
            " binary."
        ),
    )


class DetectorConfig(BaseModel):
    """
    Configuration for a specific detector.
    """

    detector_id: str = Field(..., description="Detector ID")
    local_inference_template: str = Field(..., description="Template for local edge inference.")
    motion_detection_template: str = Field(..., description="Template for motion detection.")
    edge_only: bool = Field(
        default=False,
        description="Whether the detector should be in edge-only mode or not. Optional; defaults to False.",
    )
    edge_only_inference: bool = Field(
        default=False,
        description="Whether the detector should be in edge-only inference mode or not. Optional; defaults to False.",
    )

    @validator("edge_only", "edge_only_inference")
    def validate_edge_modes(cls, v, values):
        if "edge_only" in values and "edge_only_inference" in values:
            if values["edge_only"] and values["edge_only_inference"]:
                raise ValueError("'edge_only' and 'edge_only_inference' cannot both be True")
        return v


class RootEdgeConfig(BaseModel):
    """
    Root configuration for edge inference and motion detection.
    """

    motion_detection_templates: Dict[str, MotionDetectionConfig]
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
                                    motion_detection_template='default',
                                    edge_only=False
                                )
                },
                'motion_detection_templates': {
                    'default': MotionDetectionConfig(
                                    enabled=True,
                                    percentage_threshold=0.01,
                                    val_threshold=None,
                                    max_time_between_images=3600.0
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
            if detector.motion_detection_template not in self.motion_detection_templates:
                raise ValueError(f"Motion Detection Template {detector.motion_detection_template} not defined.")
            if detector.local_inference_template not in self.local_inference_templates:
                raise ValueError(f"Local Inference Template {detector.local_inference_template} not defined.")
        return self
