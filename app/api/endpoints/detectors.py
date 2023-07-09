from fastapi import APIRouter, Depends
from starlette.requests import Request
from app.core.utils import get_groundlight_instance

from app.schemas.schemas import (
    DetectorCreate,
    DetectorCreateResponse,
    DetectorListResponse,
)
from model import Detector


router = APIRouter()


@router.post("/create", response_model=Detector)
async def create_detector(props: DetectorCreate, gl: Depends = Depends(get_groundlight_instance)):
    detector = gl.get_or_create_detector(
        name=props.name,
        query=props.query,
        confidence_threshold=props.confidence_threshold,
    )
    return detector

