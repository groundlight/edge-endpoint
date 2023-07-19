from typing import Optional

from pydantic import BaseModel, Field, confloat


class DetectorCreate(BaseModel):
    name: str = Field(description="Name of the detector")
    query: Optional[str] = Field(description="Query associated with the detector")
    confidence_threshold: Optional[confloat(ge=0.0, le=1.0)] = Field(
        0.9,
        description=(
            "If the detector's prediction is below this confidence threshold, send the image query for human review."
        ),
    )
    pipeline_config: Optional[str] = Field(None, description="Pipeline config")
