import logging
from typing import Dict, List, Optional, Union

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
    unconfident_iq_reescalation_interval: float = Field(
        60.0, description="How often to re-escalate unconfident Image queries."
    )


class LocalInferenceConfig(BaseModel):
    """
    Configuration for local edge inference on a specific detector.
    """

    enabled: bool = Field(False, description="Determines if local edge inference is enabled for a specific detector.")
    refresh_every: float = Field(
        3600.0,
        description=(
            "The refresh rate for the inference server (in seconds). This means how often to check for an updated model"
            " binary (currently unused)."
        ),
    )

    model_name: Optional[str] = Field(default=None, description="The name of the model to use for inference.")
    model_version: Optional[str] = Field(default=None, description="The version of the model to use for inference.")

    @validator("model_version", "model_name", pre=True, always=True)
    def validate_model(cls, field_value, values, field):
        """
        With Triton, there can be multiple versions for each model.
        And each version is stored in a numerically-named subdirectory.
        For more info: https://www.run.ai/guides/machine-learning-engineering/triton-inference-server

        :param field_value: The value of the field being validated.
        :param values: The values passed to the validator.
        :param field: The field being validated.
        """
        if values.get("enabled"):
            if field == "model_name" and not field_value:
                raise ValueError("`model_name` must be set if edge inference is enabled")

            if field == "model_version":
                if not field_value:
                    logger.warning("`model_version` not set. Defaulting to version=1")
                    field_value = "1"
                elif not field_value.isdigit():
                    raise ValueError(f"`model_version` must be a numeric string. Got {field_value} instead.")

        return field_value


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
    def validate_templates(
        cls, detector: DetectorConfig, values: Dict[str, Dict[str, Union[MotionDetectionConfig, LocalInferenceConfig]]]
    ):
        """
        Validate the templates referenced by the detectors.
        :param detector: The detector to validate.
        :param values: The values passed to the validator. This is a dictionary of the form:
            {
                'motion_detection_templates': {
                    'default': MotionDetectionConfig(
                                    enabled=True,
                                    percentage_threshold=0.01,
                                    val_threshold=None,
                                    max_time_between_images=3600.0
                                )
                }
                'local_inference_templates': {
                    'default': LocalInferenceConfig(
                                    enabled=True,
                                    refresh_every=3600.0,
                                    model_name='det_edgedemo',
                                    model_version='1'
                                )
                }
            }
        """

        if (
            "motion_detection_templates" in values
            and detector.motion_detection_template not in values["motion_detection_templates"]
        ):
            raise ValueError(f"Motion Detection Template {detector.motion_detection_template} not defined.")
        if (
            "local_inference_templates" in values
            and detector.local_inference_template not in values["local_inference_templates"]
        ):
            raise ValueError(f"Local Inference Template {detector.local_inference_template} not defined.")
        return detector