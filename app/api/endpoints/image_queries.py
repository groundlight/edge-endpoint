import logging
from io import BytesIO
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, Query
from model import ImageQuery
from PIL import Image

from app.core.utils import get_groundlight_sdk_instance, get_motion_detector_instance, prefixed_ksuid
from app.schemas.schemas import ImageQueryCreate

logger = logging.getLogger(__name__)


router = APIRouter()


@router.post("", response_model=ImageQuery)
async def post_image_query(
    props: ImageQueryCreate = Depends(ImageQueryCreate),
    gl: Depends = Depends(get_groundlight_sdk_instance),
    motion_detector: Depends = Depends(get_motion_detector_instance),
):
    """
    Submit an image query to the detector.
    NOTE: For now motion detection assumes that images are submitted to the
    same detector. If the client sends the same image to multiple detectors
    we would incorrectly flag no motion detected for the second detector.
    """
    image = props.image
    detector_id = props.detector_id
    wait_time = props.wait
    img = Image.open(BytesIO(image))
    img_numpy = np.array(img)

    async with motion_detector.lock:
        motion_detected = await motion_detector.motion_detected(new_img=img_numpy)

        iq_response_is_improvable = (
            motion_detector.image_query_response is not None
            and motion_detector.image_query_response.result.label == "UNSURE"
        )

        if motion_detected or iq_response_is_improvable:
            image_query = gl.submit_image_query(detector=detector_id, image=image, wait=wait_time)

            # Store the cloud's response so that if the next image has no motion, we will return
            # the same response.
            motion_detector.image_query_response = image_query
            logger.info("Motion detected")
            return image_query

    logger.info("No motion detected")

    new_image_query = ImageQuery(**motion_detector.image_query_response.dict())
    new_image_query.id = prefixed_ksuid(prefix="iqe_")
    motion_detector.image_query_response = new_image_query

    return new_image_query


@router.get("", response_model=ImageQuery)
async def handle_get_requests(
    page: Optional[int] = Query(...),
    page_size: Optional[int] = Query(...),
    query_id: Optional[str] = Query(...),
    gl: Depends = Depends(get_groundlight_sdk_instance),
):
    """
    Handles GET requests for image queries endpoint.
    """
    if query_id is not None:
        return gl.get_image_query(image_query_id=query_id)

    return gl.list_image_queries(page=page, page_size=page_size)
