import logging
from io import BytesIO

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from groundlight import Groundlight
from model import ImageQuery
from PIL import Image, ImageFile

from app.core.utils import get_groundlight_sdk_instance, get_motion_detector_instance, prefixed_ksuid

logger = logging.getLogger(__name__)


router = APIRouter()

ImageFile.LOAD_TRUNCATED_IMAGES = True


def safe_submit_image_query(gl: Groundlight, detector_id: str, image: bytes, wait: float = None) -> ImageQuery:
    """
    This ensures that we correctly handle HTTP error status codes. In some cases, for example,
    400 error codes are forwarded as 500 by FastAPI, which is not what we want.
    """
    try:
        return gl.submit_image_query(detector=detector_id, image=image, wait=wait)

    except Exception as e:
        if hasattr(e, "status"):
            raise HTTPException(status_code=e.status, detail=str(e))
        raise e


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
        return safe_submit_image_query(gl=gl, detector_id=detector_id, image=image, wait=wait)

    async with motion_detector.lock:
        motion_detected = await motion_detector.motion_detected(new_img=img_numpy)

        if motion_detected:
            image_query = safe_submit_image_query(gl=gl, detector_id=detector_id, image=image, wait=wait)
            motion_detector.image_query_response = image_query
            logger.debug("Motion detected")
            return image_query

    logger.debug("No motion detected")
    new_image_query = ImageQuery(**motion_detector.image_query_response.dict())
    new_image_query.id = prefixed_ksuid(prefix="iqe_")
    return new_image_query
