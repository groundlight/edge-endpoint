from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from groundlight import Groundlight
from model import Detector
from pydantic import BaseModel, Field

from app.core.app_state import get_groundlight_sdk_instance
from app.core.utils import safe_call_sdk

router = APIRouter()

# NOTE: the following endpoints are simple pass-throughs to the cloud-api.
# These should be removed in favor of using nginx.


class DetectorCreate(BaseModel):
    name: str = Field(description="Name of the detector")
    query: Optional[str] = Field(description="Query associated with the detector")
    group_name: Optional[str] = Field(description="Which group should this detector be part of?")
    confidence_threshold: Optional[Annotated[float, Field(ge=0.0, le=1.0)]] = Field(
        0.9,
        description=(
            "If the detector's prediction is below this confidence threshold, send the image query for human review."
        ),
    )
    pipeline_config: Optional[str] = Field(None, description="Pipeline config")


@router.post("", response_model=Detector)
async def create_detector(props: DetectorCreate, gl: Groundlight = Depends(get_groundlight_sdk_instance)):
    return safe_call_sdk(
        gl.create_detector,
        name=props.name,
        query=props.query,
        group_name=props.group_name,
        confidence_threshold=props.confidence_threshold,
        pipeline_config=props.pipeline_config,
    )


@router.get("/{id}", response_model=Detector)
async def get_detector(id: str, gl: Groundlight = Depends(get_groundlight_sdk_instance)):
    return safe_call_sdk(gl.get_detector, id=id)
