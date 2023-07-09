from fastapi import APIRouter, Depends
from typing import Union
from app.core.utils import get_groundlight_instance

from app.schemas.schemas import DetectorCreate
from model import Detector

router = APIRouter()


@router.post("", response_model=Detector)
async def get_or_create_detector(props: DetectorCreate, gl: Depends = Depends(get_groundlight_instance)):
    return gl.get_or_create_detector(
        name=props.name,
        query=props.query,
        confidence_threshold=props.confidence_threshold,
        pipeline_config=props.pipeline_config,
    )

@router.get("/get", response_model=Detector)
async def get_detector(props: Union[str, Detector], gl: Depends = Depends(get_groundlight_instance)):
    return gl.get_detector(props)
