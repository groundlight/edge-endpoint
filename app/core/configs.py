import logging
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


class MotionDetectionConfig(BaseModel):
    motion_detection_enabled: bool = Field(
        ..., description="Determines if motion detection is enabled for this detector"
    )
    motion_detection_percentage_threshold: Optional[float] = Field(
        default=None, description="Percent of pixels needed to change before motion is detected."
    )
    motion_detection_val_threshold: Optional[int] = Field(
        default=None, description="The minimum brightness change for a pixel for it to be considered changed."
    )
    motion_detection_max_time_between_images: Optional[float] = Field(
        default=None,
        description=(
            "Specifies the maximum time (seconds) between images sent to the cloud. This will be honored even if no"
            " motion has been detected. Defaults to 1 hour."
        ),
    )


class LocalInferenceConfig(BaseModel):
    enabled: bool = Field(False, description="Determines if local edge inference is enabled for a specific detector.")
    refresh_every: float = Field(3600.0, description="The refresh rate for the inference server (in seconds).")


class DetectorConfig(BaseModel):
    """
    Configuration for a specific detector.
    """

    detector_id: str = Field(..., description="Detector ID")
    local_inference_template: str = Field(..., description="Template for local edge inference.")
    motion_detection_template: str = Field(..., description="Template for motion detection.")


class RootEdgeConfig(BaseModel):
    """
    Root configuration for edge inference and motion detection.
    """

    motion_detection_template: Dict[str, MotionDetectionConfig]
    local_inference_template: Dict[str, LocalInferenceConfig]
    detectors: List[DetectorConfig]

    @validator("detectors", each_item=True)
    def validate_templates(cls, detector, values):
        if (
            "motion_detection_template" in values
            and detector.motion_detection_template not in values["motion_detection_template"]
        ):
            raise ValueError(f"Motion Detection Template {detector.motion_detection_template} not defined.")
        if (
            "local_inference_template" in values
            and detector.local_inference_template not in values["local_inference_template"]
        ):
            raise ValueError(f"Local Inference Template {detector.local_inference_template} not defined.")
        return detector
