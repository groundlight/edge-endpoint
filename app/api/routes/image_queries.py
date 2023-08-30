import logging
from io import BytesIO
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from model import ImageQuery
from PIL import Image

from app.core.utils import (
    get_groundlight_sdk_instance,
    get_iqe_cache,
    get_motion_detection_manager,
    prefixed_ksuid,
    safe_call_api,
)

logger = logging.getLogger(__name__)


router = APIRouter()


async def validate_request_body(request: Request) -> Image.Image:
    if not request.headers.get("Content-Type", "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Request body must be image bytes")

    image_bytes = await request.body()
    try:
        # Attempt to open the image
        image = Image.open(BytesIO(image_bytes))

        # Image.open() does not fully process the image data. It's possible for Image.open()
        # to succeed but then fail when the image data is actually being processed.
        # To ensure that the image can be fully processed, we call img.load() to force loading
        # the entire image. If this fails, we know that the image is invalid.

        image.load()
        return image
    except Exception:
        logger.error("Failed to load image", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid input image")


@router.post("", response_model=ImageQuery)
async def post_image_query(
    detector_id: str = Query(..., description="Detector ID"),
    patience_time: Optional[float] = Query(None, description="How long to wait for a confident response"),
    img: Image.Image = Depends(validate_request_body),
    gl: Depends = Depends(get_groundlight_sdk_instance),
    iqe_cache: Depends = Depends(get_iqe_cache),
    motion_detection_manager: Depends = Depends(get_motion_detection_manager),
):
    if (
        detector_id not in motion_detection_manager.detectors
        or not motion_detection_manager.detectors[detector_id].is_enabled()
    ):
        return safe_call_api(gl.submit_image_query, detector=detector_id, image=img, wait=patience_time)

    img_numpy = np.array(img)
    motion_detected = motion_detection_manager.run_motion_detection(detector_id=detector_id, new_img=img_numpy)

    if motion_detected:
        image_query = safe_call_api(gl.submit_image_query, detector=detector_id, image=img, wait=patience_time)
        # Store the cloud's response so that if the next image has no motion, we will return
        # the same response
        motion_detection_manager.update_image_query_response(detector_id=detector_id, response=image_query)
        return image_query

    logger.debug(f"No motion detected for {detector_id=}")
    new_image_query = ImageQuery(**motion_detection_manager.get_image_query_response(detector_id=detector_id).dict())
    new_image_query.id = prefixed_ksuid(prefix="iqe_")
    iqe_cache.update_cache(image_query=new_image_query)

    return new_image_query


@router.get("/{id}", response_model=ImageQuery)
async def get_image_query(
    id: str,
    gl: Depends = Depends(get_groundlight_sdk_instance),
    iqe_cache: Depends = Depends(get_iqe_cache),
):
    if id.startswith("iqe_"):
        image_query = iqe_cache.get_cached_image_query(image_query_id=id)
        if not image_query:
            raise HTTPException(status_code=404, detail=f"Image query with ID {id} not found")
        return image_query
    return safe_call_api(gl.get_image_query, id=id)
