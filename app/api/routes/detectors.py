from fastapi import APIRouter, Depends, Request
from model import Detector
from groundlight import Groundlight

from app.core.utils import AppState, get_app_state, safe_call_api, get_groundlight_sdk_instance
from app.schemas.schemas import DetectorCreate

router = APIRouter()


@router.post("", response_model=Detector)
async def create_detector(props: DetectorCreate, gl: Groundlight = Depends(get_groundlight_sdk_instance)):
    return safe_call_api(
        gl.create_detector,
        name=props.name,
        query=props.query,
        confidence_threshold=props.confidence_threshold,
        pipeline_config=props.pipeline_config,
    )


@router.get("/{id}", response_model=Detector)
async def get_detector(id: str, gl: Groundlight = Depends(get_groundlight_sdk_instance)):
    return safe_call_api(gl.get_detector, id=id)
