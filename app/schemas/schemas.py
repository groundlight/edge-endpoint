from pydantic import BaseModel, Field, confloat, AnyUrl, constr
from typing import Optional, List
from datetime import datetime


# class Detector(BaseModel):
#     id: str = Field(..., description="A unique ID for this object.")
#     created_at: datetime = Field(..., description="When this detector was created.")
#     name: constr(max_length=200) = Field(..., description="A short, descriptive name for the detector.")
#     query: str = Field(..., description="A question about the image.")
#     group_name: str = Field(..., description="Which group should this detector be part of?")
#     confidence_threshold: Optional[confloat(ge=0.0, le=1.0)] = Field(
#         0.9,
#         description=(
#             "If the detector's prediction is below this confidence threshold, send the image query for human review."
#         ),
#     )


class DetectorCreate(BaseModel):
    name: str = Field(description="Detector name")
    query: str = Field(description="Query associated with the detector")
    confidence_threshold: Optional[str] = Field(description="Confidence threshold")


class DetectorCreateResponse(BaseModel):
    result: str = Field(description="Create detector result")


class DetectorListResponse(BaseModel):
    count: Optional[int] = Field(description="Number of detectors", example=123)
    detector_names: Optional[List[str]] = None


class ImageQueryCreate(BaseModel):
    detector_name: str = Field(description="Detector name")
    detector_id: Optional[str] = Field(description="Detector ID")
    image: str = Field(description="Image file path")
    wait: Optional[float] = Field(description="How long to wait for a confident response (seconds)")


class ClassificationResult(BaseModel):
    confidence: Optional[confloat(ge=0.0, le=1.0)] = Field(
        None, description="On a scale of 0 to 1, how confident are we in the predicted label?"
    )
    label: str = Field(..., description="What is the predicted label?")


class ImageQueryResponse(BaseModel):
    created_at: datetime = Field(description="When was the detector created?")
    detector_id: str = Field(description="Which detector was used on this image query?")
    result: ClassificationResult
