import logging
from io import BytesIO

import numpy as np
from fastapi import APIRouter, Depends, Request
from model import ImageQuery
from PIL import Image, ImageFile

from app.core.utils import get_groundlight_sdk_instance, get_motion_detector_instance, prefixed_ksuid, safe_call_api

logger = logging.getLogger(__name__)


router = APIRouter()

ImageFile.LOAD_TRUNCATED_IMAGES = True


@router.post("", response_model=ImageQuery)
async def post_image_query(
    detector_id: str,
    wait: float = None,
    request: Request = None,
    gl: Depends = Depends(get_groundlight_sdk_instance),
    motion_detector: Depends = Depends(get_motion_detector_instance),
):
    image = await request.body()
    img = Image.open(BytesIO(image))
    img_numpy = np.array(img)

    if not motion_detector.is_enabled():
        return safe_call_api(gl.submit_image_query, detector=detector_id, image=image, wait=wait)

    async with motion_detector.lock:
        motion_detected = await motion_detector.motion_detected(new_img=img_numpy)

        if motion_detected:
            image_query = safe_call_api(gl.submit_image_query, detector=detector_id, image=image, wait=wait)
            # Store the cloud's response so that if the next image has no motion, we will return
            # the same response
            motion_detector.image_query_response = image_query
            if motion_detected:
                logger.debug("Motion detected")
            else:
                logger.debug("Maximum time between images exceeded")
            return image_query

    logger.debug("No motion detected")
    new_image_query = ImageQuery(**motion_detector.image_query_response.dict())
    new_image_query.id = prefixed_ksuid(prefix="iqe_")
    return new_image_query


@router.get("/{id}", response_model=ImageQuery)
async def get_image_query(id: str, gl: Depends = Depends(get_groundlight_sdk_instance)):
    return safe_call_api(gl.get_image_query, id=id)
