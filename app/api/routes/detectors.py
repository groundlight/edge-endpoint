import logging

from fastapi import APIRouter, Depends
from model import Detector

from app.core.utils import get_groundlight_sdk_instance, safe_call_api
from app.schemas.schemas import DetectorCreate

logger = logging.getLogger(__name__)


router = APIRouter()


@router.post("", response_model=Detector)
async def create_detector(props: DetectorCreate, gl: Depends = Depends(get_groundlight_sdk_instance)):
    return safe_call_api(
        gl.create_detector,
        name=props.name,
        query=props.query,
        confidence_threshold=props.confidence_threshold,
        pipeline_config=props.pipeline_config,
    )


@router.get("/{id}", response_model=Detector)
async def get_detector(id: str, gl: Depends = Depends(get_groundlight_sdk_instance)):
    return safe_call_api(gl.get_detector, id=id)
