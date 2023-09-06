import logging
from datetime import datetime
from io import BytesIO
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from model import ClassificationResult, ImageQuery, ImageQueryTypeEnum, ResultTypeEnum
from PIL import Image

from app.core.edge_inference import edge_inference, edge_inference_is_available
from app.core.utils import (
    get_groundlight_sdk_instance,
    get_inference_client,
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
    except Exception as ex:  # TODO: Specify the exact exceptions we want to catch, eliminate bare except
        logger.error("Failed to load image", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid input image") from ex


@router.post("", response_model=ImageQuery)
async def post_image_query(
    detector_id: str = Query(..., description="Detector ID"),
    patience_time: Optional[float] = Query(None, description="How long to wait for a confident response"),
    img: Image.Image = Depends(validate_request_body),
    gl: Depends = Depends(get_groundlight_sdk_instance),
    iqe_cache: Depends = Depends(get_iqe_cache),
    motion_detection_manager: Depends = Depends(get_motion_detection_manager),
    inference_client: Depends = Depends(get_inference_client),
):
    """
    Submit an image query for a given detector.
    For detectors on which motion detection is enabled, this will use short-circuiting to return a cached
    response from the last image query response.
    In addition, this will also attempt to run inference locally on the edge if the edge inference server is available
    before deciding to submit the image to the cloud.

    :param detector_id: which detector to use
    :param patience_time: how long to wait for a confident response
    :param img: the image to submit.
    :param gl: Application's Groundlight SDK instance
    :param iqe_cache: Application's image query ID cache.
        When no motion is detected for the current image, we generate a new image query prefixed with "iqe_".
        We cache all such "iqe_" image queries in the iqe_cache so that we can better handle calls to `get_image_query`
        for these image queries.

    :param motion_detection_manager: Application's motion detection manager instance.
        This manages the motion detection state for all detectors.
    :param inference_client: Application's triton inference client.
    """
    img_numpy = np.array(img)  # [H, W, C=3], dtype: uint8, RGB format

    if (
        detector_id in motion_detection_manager.detectors
        and motion_detection_manager.detectors[detector_id].is_enabled()
    ):
        motion_detected = motion_detection_manager.run_motion_detection(detector_id=detector_id, new_img=img_numpy)
        if not motion_detected:
            detector = gl.get_detector(id=detector_id)
            cached_image_query = motion_detection_manager.get_image_query_response(detector_id=detector_id)
            desired_detector_confidence = detector.confidence_threshold

            iq_confidence_is_improvable = (
                cached_image_query.result.confidence is not None
                and cached_image_query.result.confidence < desired_detector_confidence
            )

            if iq_confidence_is_improvable:
                logger.debug(
                    f"Image query confidence is improvable for {detector_id=}. Current confidence:"
                    f" {cached_image_query.result.confidence}, desired confidence: {desired_detector_confidence}"
                )
                iq_response = safe_call_api(gl.get_image_query, id=cached_image_query.id)
                unconfident_iq_reescalation_interval_exceeded = motion_detection_manager.detectors[
                    detector_id
                ].unconfident_iq_reescalation_interval_exceeded()

                # There's a subtlety here since confidence=None implies human label, which is treated as confident
                confidence_is_improved = (
                    iq_response.result.confidence is None
                    or iq_response.result.confidence > cached_image_query.result.confidence
                )

                if not unconfident_iq_reescalation_interval_exceeded and confidence_is_improved:
                    logger.debug(
                        f"Image query confidence has improved for {detector_id=}. New confidence:"
                        f" {iq_response.result.confidence}"
                    )
                    # Replace the cached image query response with the new one since it has a higher confidence
                    motion_detection_manager.update_image_query_response(detector_id=detector_id, response=iq_response)

                elif unconfident_iq_reescalation_interval_exceeded:
                    # If the unconfident image query re-escalation interval has been exceeded, we re-escalate the image
                    # query to the cloud server.
                    new_image_query = safe_call_api(
                        gl.submit_image_query, detector=detector_id, image=img, wait=patience_time
                    )
                    motion_detection_manager.update_image_query_response(
                        detector_id=detector_id, response=new_image_query
                    )
                    return new_image_query

            # If there is no motion, return a clone of the last image query response
            logger.debug(f"No motion detected for {detector_id=}")
            new_image_query = motion_detection_manager.get_image_query_response(detector_id=detector_id).copy(
                deep=True, update={"id": prefixed_ksuid(prefix="iqe_")}
            )
            iqe_cache.update_cache(image_query=new_image_query)
            return new_image_query

    # Try to submit the image to a local edge detector
    model_name, confidence_threshold = "det_edgedemo", 0.9
    image_query = None
    if edge_inference_is_available(inference_client, model_name):
        results = edge_inference(inference_client, img_numpy, model_name)
        if results["confidence"] > confidence_threshold:
            logger.info("Edge detector confidence is high enough to return")

            detector = gl.get_detector(id=detector_id)
            image_query = _create_image_query(
                detector_id=detector_id,
                label=results["label"],
                confidence=results["confidence"],
                query=detector.query,
            )

    # Finally, fall back to submitting the image to the cloud
    if not image_query:
        image_query = safe_call_api(gl.submit_image_query, detector=detector_id, image=img, wait=patience_time)

    if (
        detector_id in motion_detection_manager.detectors
        and motion_detection_manager.detectors[detector_id].is_enabled()
    ):
        # Store the cloud's response so that if the next image has no motion, we will return the same response
        motion_detection_manager.update_image_query_response(detector_id=detector_id, response=image_query)

    return image_query


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


def _create_image_query(detector_id: str, label: str, confidence: float, query: str = "") -> ImageQuery:
    iq = ImageQuery(
        id=prefixed_ksuid(prefix="iqe_"),
        type=ImageQueryTypeEnum.image_query,
        created_at=datetime.utcnow(),
        query=query,
        detector_id=detector_id,
        result_type=ResultTypeEnum.binary_classification,
        result=ClassificationResult(
            confidence=confidence,
            label=label,
        ),
    )
    return iq
