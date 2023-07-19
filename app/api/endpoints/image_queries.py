import logging
from io import BytesIO
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, Query, Request
from model import ImageQuery
from PIL import Image

from app.core.utils import get_groundlight_sdk_instance, get_motion_detector_instance, prefixed_ksuid

logger = logging.getLogger(__name__)


router = APIRouter()


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

    async with motion_detector.lock:
        motion_detected = await motion_detector.motion_detected(new_img=img_numpy)

        iq_response_is_improvable = (
            motion_detector.image_query_response is not None
            and motion_detector.image_query_response.result.label == "UNSURE"
        )

        if motion_detected or iq_response_is_improvable:
            image_query = gl.submit_image_query(detector=detector_id, image=image, wait=wait)
            motion_detector.image_query_response = image_query
            logger.debug("Motion detected")
            return image_query

    logger.debug("No motion detected")
    new_image_query = ImageQuery(**motion_detector.image_query_response.dict())
    new_image_query.id = prefixed_ksuid(prefix="iqe_")
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
