import logging

from fastapi import APIRouter, Depends
from model import ImageQuery

from app.core.utils import get_groundlight_instance
from app.schemas.schemas import ImageQueryCreate

logger = logging.getLogger(__name__)


router = APIRouter()


@router.post("/submit", response_model=ImageQuery)
async def post_image_query(props: ImageQueryCreate, gl: Depends = Depends(get_groundlight_instance)):
    """
    Submit an image query to the detector.
    """
    detector_name = props.detector_name
    wait_time = props.wait
    detector = gl.get_detector_by_name(name=detector_name)
    image_query = gl.submit_image_query(detector=detector, image=props.image, wait=wait_time)
    return image_query
