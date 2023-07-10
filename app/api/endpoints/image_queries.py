import logging

from fastapi import APIRouter, Depends, Query
from model import ImageQuery

from app.core.utils import get_groundlight_instance, get_motion_detector_instance
from app.schemas.schemas import ImageQueryCreate

logger = logging.getLogger(__name__)


router = APIRouter()


@router.post("", response_model=ImageQuery)
async def post_image_query(
    props: ImageQueryCreate = Depends(ImageQueryCreate),
    gl: Depends = Depends(get_groundlight_instance),
    motion_detector: Depends = Depends(get_motion_detector_instance),
):
    """
    Submit an image query to the detector.
    NOTE: For now motion detection assumes that images are being to the
    same detector. If the client sends the same image to multiple detectors
    we would flag incorrectly flag no motion detected for the second detector.
    """
    image = props.image
    detector_id = props.detector_id
    wait_time = props.wait

    async with motion_detector.lock:
        motion_detected = await motion_detector.detect_motion(image)
        if motion_detected:
            image_query = gl.submit_image_query(detector=detector_id, image=image, wait=wait_time)

            motion_detector.image_query_response = image_query
            logger.info("Motion detected")
            return image_query

    logger.info("No motion detected")
    return motion_detector.image_query_response


@router.get("", response_model=ImageQuery)
async def get_image_query(props: str = Query(...), gl: Depends = Depends(get_groundlight_instance)):
    """
    Get an image query by ID.
    """
    return gl.get_image_query(image_query_id=props)
