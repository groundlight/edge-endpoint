from fastapi import APIRouter, Depends
from model import Detector

from app.core.utils import AppState, get_app_state, safe_call_api
from app.schemas.schemas import DetectorCreate

router = APIRouter()


@router.post("", response_model=Detector)
async def create_detector(props: DetectorCreate, app_state: AppState = Depends(get_app_state)):
    gl = app_state.get_groundlight_sdk_instance()
    return safe_call_api(
        gl.create_detector,
        name=props.name,
        query=props.query,
        confidence_threshold=props.confidence_threshold,
        pipeline_config=props.pipeline_config,
    )


@router.get("/{id}", response_model=Detector)
async def get_detector(id: str, app_state: AppState = Depends(get_app_state)):
    gl = app_state.get_groundlight_sdk_instance()
    return safe_call_api(gl.get_detector, id=id)
