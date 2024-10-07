import logging
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator, ValidationInfo

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
        False, description="Whether the detector should be in edge-only mode or not. Optional; defaults to False."
    )
    edge_only_inference: bool = Field(
        False,
        description="Whether the detector should be in edge-only inference mode or not. Optional; defaults to False.",
    )

    @field_validator('edge_only', 'edge_only_inference')
    @classmethod
    def validate_edge_modes(cls, v, info):
        if 'edge_only' in info.data and 'edge_only_inference' in info.data:
            if info.data['edge_only'] and info.data['edge_only_inference']:
                raise ValueError("'edge_only' and 'edge_only_inference' cannot both be True")
        return v


class RootEdgeConfig(BaseModel):
    """
    Root configuration for edge inference and motion detection.
    """

    motion_detection_templates: Dict[str, MotionDetectionConfig]
    local_inference_templates: Dict[str, LocalInferenceConfig]
    detectors: Dict[str, DetectorConfig]

    @field_validator("detectors")
    @classmethod
    def validate_templates(
        cls,
        detectors: Dict[str, DetectorConfig],
        info: ValidationInfo,
    ):
        """
        Validate the templates referenced by the detectors.
        """
        for detector in detectors.values():
            if (
                "motion_detection_templates" in info.data
                and detector.motion_detection_template not in info.data["motion_detection_templates"]
            ):
                raise ValueError(f"Motion Detection Template {detector.motion_detection_template} not defined.")
            if (
                "local_inference_templates" in info.data
                and detector.local_inference_template not in info.data["local_inference_templates"]
            ):
                raise ValueError(f"Local Inference Template {detector.local_inference_template} not defined.")
        return detectors
