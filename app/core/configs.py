import logging
from typing import Optional

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

logger = logging.getLogger(__name__)


class DetectorConfig(BaseModel):
    """
    Configuration for a specific detector.
    """

    detector_id: str = Field(..., description="Detector ID")
    enabled: bool = Field(default=False, description="True if edge-inference is enabled for a specific detector.")
    api_token: Optional[str] = Field(
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
            "Only applies when `always_return_edge_prediction=True` and `disable_cloud_escalation=False`."
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

    refresh_rate: float = Field(
        default=60.0,
        description="The interval (in seconds) at which the inference server checks for a new model binary update.",
    )
    detectors: dict[str, DetectorConfig]
