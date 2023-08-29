import logging
from io import BytesIO
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from model import ImageQuery
from PIL import Image, ImageFile

from app.core.edge_inference import edge_inference, edge_inference_is_available
from app.core.utils import (
    get_edge_detector_manager,
    get_groundlight_sdk_instance,
    get_inference_client,
    get_motion_detector_instance,
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
    motion_detector: Depends = Depends(get_motion_detector_instance),
    edge_detector_manager: Depends = Depends(get_edge_detector_manager),
    inference_client: Depends = Depends(get_inference_client),
):
    image = await request.body()
    img = Image.open(BytesIO(image))
    img_numpy = np.array(img)  # [H, W, C=3], dtype: uint8, RGB format

    if motion_detector.is_enabled():
        motion_detected = motion_detector.motion_detected(new_img=img_numpy)
        if not motion_detected:
            # If there is no motion, return a clone of the last image query response
            logger.debug("No motion detected")
            new_image_query = ImageQuery(**motion_detector.image_query_response.dict())
            new_image_query.id = prefixed_ksuid(prefix="iqe_")
            edge_detector_manager.iqe_cache[new_image_query.id] = new_image_query

            return new_image_query

    # Try to submit the image to a local edge detector
    model_name = "det_edgedemo"
    if edge_inference_is_available(inference_client, model_name):
        results = edge_inference(inference_client, img_numpy, model_name)
        if results["confidence"] > 0.9:
            logger.info("Edge detector confidence is high enough to return")

    # Finally, fall back to submitting the image to the cloud
    image_query = safe_call_api(gl.submit_image_query, detector=detector_id, image=image, wait=patience_time)

    # Store the cloud's response so that if the next image has no motion, we will return the same response
    motion_detector.image_query_response = image_query
    return image_query

@router.get("/{id}", response_model=ImageQuery)
async def get_image_query(
    id: str,
    gl: Depends = Depends(get_groundlight_sdk_instance),
    edge_detector_manager: Depends = Depends(get_edge_detector_manager),
):
    if id.startswith("iqe_"):
        image_query = edge_detector_manager.iqe_cache.get(id, None)
        if not image_query:
            raise HTTPException(status_code=404, detail=f"Image query with ID {id} not found")
        return image_query
    return safe_call_api(gl.get_image_query, id=id)