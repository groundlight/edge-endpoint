import logging
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, validator

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


class LocalInferenceConfig(BaseModel):
    """
    Configuration for local edge inference on a specific detector.
    """
    
    enabled: bool = Field(False, description="Determines if local edge inference is enabled for a specific detector.")
    refresh_every: float = Field(3600.0, description="The refresh rate for the inference server (in seconds).")
    
    model_name: Optional[str] = Field(default=None, description="The name of the model to use for inference.")
    model_version: Optional[str] = Field(default=None, description="The version of the model to use for inference.")

    @validator("model_version", always=True)
    def validate_model_version(cls, model_version, values):
        """
        With Triton, there can be multiple versions of each model.
        And each version is stored in a numerically-named subdirectory.
        For more info: https://www.run.ai/guides/machine-learning-engineering/triton-inference-server
        """
        if values.get("model_name") and not model_version:
            raise ValueError("`model_version` must be set if `model_name` is set")

        if model_version is not None and not model_version.isdigit():
            raise ValueError("`model_version` must be a numeric string. Got {v} instead.")
        return model_version


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

    motion_detection_templates: Dict[str, MotionDetectionConfig]
    local_inference_templates: Dict[str, LocalInferenceConfig]
    detectors: List[DetectorConfig]

    @validator("detectors", each_item=True)
    def validate_templates(cls, detector: DetectorConfig, values: Dict[str, str]):
        """
        Validate the templates referenced by the detectors.
        :param detector: The detector to validate.
        :param values: The values passed to the validator. 
        """
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
