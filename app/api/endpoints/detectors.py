import logging
from fastapi import APIRouter, Depends, Path, Body
from model import Detector

from app.core.utils import get_groundlight_instance
from app.schemas.schemas import DetectorCreateAndGet, PaginationParams
from fastapi import Query

logger = logging.getLogger(__name__)


router = APIRouter()


@router.post("", response_model=Detector)
async def create_detector(props: DetectorCreateAndGet, gl: Depends = Depends(get_groundlight_instance)):
    return gl.get_or_create_detector(
        name=props.name,
        query=props.query,
        confidence_threshold=props.confidence_threshold,
        pipeline_config=props.pipeline_config,
    )


@router.get("", response_model=Detector)
async def get_or_create_detector(
    props: DetectorCreateAndGet = Depends(), gl: Depends = Depends(get_groundlight_instance)
):
    return gl.get_or_create_detector(
        name=props.name,
        query=props.query,
        confidence_threshold=props.confidence_threshold,
        pipeline_config=props.pipeline_config,
    )
