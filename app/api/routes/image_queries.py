import logging
from io import BytesIO
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from model import ImageQuery
from PIL import Image, ImageFile

from app.core.utils import (
    get_edge_detector_manager,
    get_groundlight_sdk_instance,
    get_motion_detector_instance,
    get_motion_detection_manager,
    prefixed_ksuid,
    safe_call_api,
)

logger = logging.getLogger(__name__)


router = APIRouter()

ImageFile.LOAD_TRUNCATED_IMAGES = True


@router.post("", response_model=ImageQuery)
async def post_image_query(
    detector_id: str = Query(..., description="Detector ID"),
    patience_time: Optional[float] = Query(None, description="How long to wait for a confident response"),
    request: Request = None,
    gl: Depends = Depends(get_groundlight_sdk_instance),
    edge_detector_manager: Depends = Depends(get_edge_detector_manager),
    motion_detection_manager: Depends = Depends(get_motion_detection_manager),
):
    image = await request.body()
    img = Image.open(BytesIO(image))
    img_numpy = np.array(img)

    if (
        detector_id not in motion_detection_manager.detectors
        or not motion_detection_manager.detectors[detector_id].is_enabled()
    ):
        return safe_call_api(gl.submit_image_query, detector=detector_id, image=image, wait=patience_time)

    motion_detected = motion_detection_manager.run_motion_detection(detector_id=detector_id, new_img=img_numpy)

    if motion_detected:
        image_query = safe_call_api(gl.submit_image_query, detector=detector_id, image=image, wait=patience_time)
        # Store the cloud's response so that if the next image has no motion, we will return
        # the same response
        motion_detection_manager.update_image_query_response(detector_id=detector_id, response=image_query)
        return image_query

    logger.debug(f"No motion detected for {detector_id=}")
    new_image_query = ImageQuery(**motion_detection_manager.get_image_query_response(detector_id=detector_id).dict())
    new_image_query.id = prefixed_ksuid(prefix="iqe_")
    edge_detector_manager.update_cache(detector_id=detector_id, image_query=new_image_query)

    return new_image_query


@router.get("/{id}", response_model=ImageQuery)
async def get_image_query(
    id: str,
    gl: Depends = Depends(get_groundlight_sdk_instance),
    edge_detector_manager: Depends = Depends(get_edge_detector_manager),
):
    if id.startswith("iqe_"):
        image_query = edge_detector_manager.get_cached_image_query(image_query_id=id)
        if not image_query:
            raise HTTPException(status_code=404, detail=f"Image query with ID {id} not found")
        return image_query
    return safe_call_api(gl.get_image_query, id=id)
