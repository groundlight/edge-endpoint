import logging

from fastapi import APIRouter, Depends, Query
from model import ImageQuery

from app.core.utils import get_groundlight_instance
from app.schemas.schemas import ImageQueryCreate

logger = logging.getLogger(__name__)


router = APIRouter()


@router.post("", response_model=ImageQuery)
async def post_image_query(
    props: ImageQueryCreate = Depends(ImageQueryCreate), gl: Depends = Depends(get_groundlight_instance)
):
    """
    Submit an image query to the detector.
    """
    image = props.image
    detector_id = props.detector_id
    wait_time = props.wait
    image_query = gl.submit_image_query(detector=detector_id, image=image, wait=wait_time)
    return image_query


@router.get("", response_model=ImageQuery)
async def get_image_query(props: str = Query(...), gl: Depends = Depends(get_groundlight_instance)):
    """
    Get an image query by ID.
    """
    return gl.get_image_query(image_query_id=props)
