import logging
from typing import Dict, Optional, Union

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


class RootEdgeConfig(BaseModel):
    """
    Root configuration for edge inference and motion detection.
    """

    motion_detection_templates: Dict[str, MotionDetectionConfig]
    local_inference_templates: Dict[str, LocalInferenceConfig]
    detectors: Dict[str, DetectorConfig]

    @validator("detectors", each_item=False)
    @classmethod
    def validate_templates(
        cls,
        detectors: Dict[str, DetectorConfig],
        values: Dict[str, Dict[str, Union[MotionDetectionConfig, LocalInferenceConfig]]],
    ):
        """
        Validate the templates referenced by the detectors.
        :param detectors: The detectors to validate.
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
                                    refresh_rate=120.0
                                )
                }
            }
        """
        for detector in detectors.values():
            missing_templates = [
                ("motion_detection_templates", detector.motion_detection_template),
                ("local_inference_templates", detector.local_inference_template),
            ]

            for template_type, template_name in missing_templates:
                if template_type in values and template_name not in values[template_type]:
                    raise ValueError(f"{template_type.replace('_', ' ').title()} {template_name} not defined.")

            return detectors
