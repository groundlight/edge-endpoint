from datetime import datetime
from typing import List, Optional, Union

from pydantic import BaseModel, Field, validator
from model import Detector, ImageQuery, ClassificationResult, PaginatedImageQueryList, PaginatedDetectorList
from PIL import Image
from io import BytesIO, BufferedReader
import numpy as np


class DetectorCreate(BaseModel):
    query: str = Field(description="Query associated with the detector")
    confidence_threshold: Optional[str] = Field(description="Confidence threshold")


class DetectorCreateResponse(BaseModel):
    result: str = Field(description="Create detector result")


class DetectorListResponse(BaseModel):
    count: Optional[int] = Field(description="Number of detectors", example=123)
    detector_names: Optional[List[str]] = None

    
class ImageQueryCreate(BaseModel):
    """
    NOTE: For the `image` field, types BytesIO, BufferedReader, Image.Image 
    and numpy.ndarray are not JSON compatible. For now we are only supporting
    str and bytes types although the SDK accepts all the above. 
    Reference: https://fastapi.tiangolo.com/tutorial/encoder/
    """
    detector_name: Optional[str] = Field(description="Detector name")
    detector_id: str = Field(description="Detector ID")
    image: Union[str, bytes] = Field(
        description="Image to submit to the detector."
    )
    wait: Optional[float] = Field(description="How long to wait for a confident response (seconds)")

