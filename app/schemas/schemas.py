from typing import Optional

from pydantic import BaseModel, Field
from typing_extensions import Annotated


class DetectorCreate(BaseModel):
    name: str = Field(description="Name of the detector")
    query: Optional[str] = Field(default=None, description="Query associated with the detector")
    group_name: Optional[str] = Field(default=None, description="Which group should this detector be part of?")
    confidence_threshold: Optional[Annotated[float, Field(ge=0.0, le=1.0)]] = Field(
        0.9,
        description=(
            "If the detector's prediction is below this confidence threshold, send the image query for human review."
        ),
    )
    pipeline_config: Optional[str] = Field(None, description="Pipeline config")


class ImageQueryCreate(BaseModel):
    detector_id: str = Field(description="Detector ID")
    wait: float = Field(None, description="How long to wait for a confident response")
