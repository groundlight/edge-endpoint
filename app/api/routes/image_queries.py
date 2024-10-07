import logging
from io import BytesIO
from typing import Optional

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from groundlight import Groundlight
from model import Detector, ImageQuery, ModeEnum, ResultTypeEnum
from PIL import Image

from app.core import constants
from app.core.app_state import (
    AppState,
    get_app_state,
    get_detector_metadata,
    get_groundlight_sdk_instance,
)
from app.core.motion_detection import MotionDetectionManager
from app.core.utils import create_iqe, prefixed_ksuid, safe_call_api

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


async def validate_query_params_for_edge(request: Request, invalid_edge_params: set):
    query_params = set(request.query_params.keys())
    invalid_provided_params = query_params.intersection(invalid_edge_params)
    if invalid_provided_params:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid query parameters for submit_image_query to edge-endpoint: {invalid_provided_params}",
        )


@router.post("", response_model=ImageQuery)
async def post_image_query(
    request: Request,
    detector_id: str = Query(...),
    image: Image.Image = Depends(validate_request_body),
    patience_time: Optional[float] = Query(None),
    confidence_threshold: Optional[float] = Query(None),
    human_review: Optional[str] = Query(None),
    want_async: Optional[str] = Query(None),
    gl: Groundlight = Depends(get_groundlight_sdk_instance),
    app_state: AppState = Depends(get_app_state),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Submit an image query for a given detector.
    For detectors on which motion detection is enabled, this will use short-circuiting to return a cached
    response from the last image query response.
    In addition, this will also attempt to run inference locally on the edge if the edge inference server is available
    before deciding to submit the image to the cloud.

    :param detector_id: the string id of the detector to use, like `det_12345`

    :param image: the image to submit.

    :param patience_time: How long to wait (in seconds) for a confident answer for this image query.
        The longer the patience_time, the more likely Groundlight will arrive at a confident answer.
        Within patience_time, Groundlight will update ML predictions based on stronger findings,
        and, additionally, Groundlight will prioritize human review of the image query if necessary.
        This is a soft server-side timeout. If not set, use the detector's patience_time.

    :param confidence_threshold: The confidence threshold to wait for.
        If not set, use the detector's confidence threshold.

    :param human_review: If `None` or `DEFAULT`, send the image query for human review
        only if the ML prediction is not confident.
        If set to `ALWAYS`, always send the image query for human review.
        If set to `NEVER`, never send the image query for human review.

    :param want_async: If True, the client will return as soon as the image query is submitted and will not wait for
        an ML/human prediction. The returned `ImageQuery` will have a `result` of None. Must set `wait` to 0 to use
        want_async.

    :param gl: Application's Groundlight SDK instance

    :param app_state: Application's state manager. It contains global state for motion detection, IQE cache, and holds
        reference to the edge inference manager.
    """
    await validate_query_params_for_edge(
        request,
        invalid_edge_params={
            "inspection_id",  # inspection_id will not be supported on the edge
            "metadata",  # metadata is not supported on the edge currently, we need to set up persistent storage first
        },
    )

    detector_config = app_state.edge_config.detectors.get(detector_id, None)
    edge_only = detector_config.edge_only if detector_config is not None else False
    edge_only_inference = detector_config.edge_only_inference if detector_config is not None else False

    # TODO: instead of just forwarding want_async calls to the cloud, facilitate partial
    #       processing of the async request on the edge before escalating to the cloud.
    _want_async = want_async is not None and want_async.lower() == "true"
    if _want_async and not (
        edge_only or edge_only_inference
    ):  # If edge-only mode is enabled, we don't want to make cloud API calls
        logger.debug(f"Submitting ask_async image query to cloud API server for {detector_id=}")
        return safe_call_api(
            gl.submit_image_query,
            detector=detector_id,
            image=image,
            wait=0,
            patience_time=patience_time,
            confidence_threshold=confidence_threshold,
            human_review=human_review,
            want_async=True,
        )

    motion_detection_manager = app_state.motion_detection_manager
    edge_inference_manager = app_state.edge_inference_manager
    require_human_review = human_review == "ALWAYS"

    if not require_human_review and motion_detection_manager.motion_detection_is_available(detector_id=detector_id):
        img_numpy = np.asarray(image)  # [H, W, C=3], dtype: uint8, RGB format
        motion_detected = motion_detection_manager.run_motion_detection(detector_id=detector_id, new_img=img_numpy)
        # TODO motion detection logic will likely need to be altered to work with edge-only mode
        if not motion_detected:
            # Try improving the cached image query response's confidence
            # (if the cached response has low confidence)
            _improve_cached_image_query_confidence(
                gl=gl,
                detector_id=detector_id,
                motion_detection_manager=motion_detection_manager,
                img=image,
            )

            # If there is no motion, return a clone of the last image query response
            logger.debug(f"No motion detected for {detector_id=}")
            new_image_query = motion_detection_manager.get_image_query_response(detector_id=detector_id).copy(
                deep=True, update={"id": prefixed_ksuid(prefix="iqe_")}
            )

            if new_image_query.result and _is_confident_enough(
                confidence=new_image_query.result.confidence,
                detector_metadata=get_detector_metadata(detector_id=detector_id, gl=gl),
                confidence_threshold=confidence_threshold,
            ):
                logger.debug("Motion detection confidence is high enough to return.")
                app_state.db_manager.create_iqe_record(record=new_image_query)
                return new_image_query

    image_query = None
    if not require_human_review and edge_inference_manager.inference_is_available(detector_id=detector_id):
        detector_metadata: Detector = get_detector_metadata(detector_id=detector_id, gl=gl)
        logger.debug(f"Local inference is available for {detector_id=}. Running inference...")
        results = edge_inference_manager.run_inference(detector_id=detector_id, image=image)
        confidence = results["confidence"]

        if (
            edge_only
            or edge_only_inference
            or _is_confident_enough(
                confidence=confidence,
                detector_metadata=get_detector_metadata(detector_id=detector_id, gl=gl),
                confidence_threshold=confidence_threshold,
            )
        ):
            if edge_only:
                logger.info(
                    "Edge-only mode is enabled on this detector. The edge model's answer will be returned "
                    f"regardless of confidence. {detector_id=}"
                )
            elif edge_only_inference:
                logger.info(
                    "Edge-only inference mode is enabled on this detector. The edge model's answer will be "
                    "returned regardless of confidence, but will still be escalated to the cloud if the confidence "
                    "is not high enough. "
                    f"{detector_id=}"
                )
            else:
                logger.info(f"Edge detector confidence is high enough to return. {detector_id=}")

            if patience_time is None:
                patience_time = constants.DEFAULT_PATIENCE_TIME  # Default patience time

            if confidence_threshold is None:
                confidence_threshold = detector_metadata.confidence_threshold  # Use detector's confidence threshold

            mode = detector_metadata.mode
            if mode == ModeEnum.BINARY:
                result_type = ResultTypeEnum.binary_classification
                results["label"] = "NO" if results["label"] else "YES"  # Map false / 0 to "YES" and true / 1 to "NO"
            elif mode == ModeEnum.COUNT:
                result_type = ResultTypeEnum.counting
            elif mode == ModeEnum.MULTI_CLASS:
                result_type = ResultTypeEnum.multi_classification
            else:
                raise ValueError(f"Got unrecognized detector mode: {mode}")

            image_query = create_iqe(
                detector_id=detector_id,
                result_type=result_type,
                label=results["label"],
                confidence=confidence,
                query=detector_metadata.query,
                confidence_threshold=confidence_threshold,
                patience_time=patience_time,
                rois=results["rois"],
                text=results["text"],
            )
            app_state.db_manager.create_iqe_record(record=image_query)

            if edge_only_inference and not _is_confident_enough(
                confidence=confidence,
                detector_metadata=get_detector_metadata(detector_id=detector_id, gl=gl),
                confidence_threshold=confidence_threshold,
            ):
                logger.info("Escalating to the cloud API server for future training due to low confidence.")
                background_tasks.add_task(safe_call_api, gl.ask_async, detector=detector_id, image=image)
        else:
            logger.info(
                "Ran inference locally, but detector confidence is not high enough to return. Current confidence:"
                f" {confidence} is less than confidence threshold: {detector_metadata.confidence_threshold}."
                " Escalating to the cloud API server."
            )
    else:
        # Add a record to the inference deployments table to indicate that a k8s inference deployment has not yet been
        # created for this detector.
        api_token = gl.api_client.configuration.api_key["ApiToken"]
        logger.debug(f"Local inference not available for {detector_id=}. Creating inference deployment record.")
        app_state.db_manager.create_inference_deployment_record(
            record={
                "detector_id": detector_id,
                "api_token": api_token,
                "deployment_created": False,
            }
        )

        # Fail if edge inference is not available and edge-only mode is enabled
        if edge_only:
            raise RuntimeError("Edge-only mode is enabled on this detector, but edge inference is not available.")
        elif edge_only_inference:
            raise RuntimeError(
                "Edge-only inference mode is enabled on this detector, but edge inference is not available."
            )

    # Finally, fall back to submitting the image to the cloud
    if not image_query:
        logger.debug(f"Submitting image query to cloud API server for {detector_id=}")
        # NOTE: Waiting is done on the customer's client, not here. Otherwise we would be blocking the
        # response to the customer's client from the edge-endpoint for many seconds. This has the
        # side effect of not allowing customers to update their detector's patience_time through the
        # edge-endpoint. But instead we could ask them to do that through the web app.
        # wait=0 sets patience_time=DEFAULT_PATIENCE_TIME and disables polling.
        image_query = safe_call_api(
            gl.submit_image_query,
            detector=detector_id,
            image=image,
            wait=0,
            patience_time=patience_time,
            confidence_threshold=confidence_threshold,
            human_review=human_review,
        )
        # TODO: patch in the edge inference results if the cloud results are not confident enough?

    if motion_detection_manager.motion_detection_is_enabled(detector_id=detector_id):
        # Store the cloud's response so that if the next image has no motion, we will return the same response
        motion_detection_manager.update_image_query_response(detector_id=detector_id, response=image_query)

    return image_query


@router.get("/{id}", response_model=ImageQuery)
async def get_image_query(
    id: str, gl: Groundlight = Depends(get_groundlight_sdk_instance), app_state: AppState = Depends(get_app_state)
):
    if id.startswith("iqe_"):
        image_query = app_state.db_manager.get_iqe_record(image_query_id=id)
        if not image_query:
            raise HTTPException(status_code=404, detail=f"Image query with ID {id} not found")
        return image_query
    return safe_call_api(gl.get_image_query, id=id)


def _improve_cached_image_query_confidence(
    gl: Groundlight,
    detector_id: str,
    motion_detection_manager: MotionDetectionManager,
    img: Image.Image,
) -> None:
    """
    Attempt to improve the confidence of the cached image query response for a given detector.
    :param gl: Application's Groundlight SDK instance
    :param detector_id: which detector to use
    :param motion_detection_manager: Application's motion detection manager instance.
        This manages the motion detection state for all detectors.
    :param img: the image to submit.
    :param metadata: Optional metadata to attach to the image query.
    """

    detector_metadata: Detector = get_detector_metadata(detector_id=detector_id, gl=gl)
    desired_detector_confidence = detector_metadata.confidence_threshold
    cached_image_query = motion_detection_manager.get_image_query_response(detector_id=detector_id)

    iq_confidence_is_improvable = (
        cached_image_query.result.confidence is not None
        and cached_image_query.result.confidence < desired_detector_confidence
    )

    if not iq_confidence_is_improvable:
        return

    logger.debug(
        f"Image query confidence is improvable for {detector_id=}. Current confidence:"
        f" {cached_image_query.result.confidence}, desired confidence: {desired_detector_confidence}"
    )
    unconfident_iq_reescalation_interval_exceeded = motion_detection_manager.detectors[
        detector_id
    ].unconfident_iq_reescalation_interval_exceeded()

    iq_response = safe_call_api(gl.get_image_query, id=cached_image_query.id)

    confidence_is_improved = (
        iq_response.result.confidence is None or iq_response.result.confidence > cached_image_query.result.confidence
    )

    if confidence_is_improved:
        logger.debug(
            f"Image query confidence has improved for {detector_id=}. New confidence: {iq_response.result.confidence}"
        )
        # Replace the cached image query response with the new one since it has a higher confidence
        motion_detection_manager.update_image_query_response(detector_id=detector_id, response=iq_response)

    elif unconfident_iq_reescalation_interval_exceeded:
        logger.debug(
            f"Unconfident image query re-escalation interval exceeded for {detector_id=}."
            " Re-escalating image query to the cloud API server"
        )
        iq_response = safe_call_api(gl.submit_image_query, detector=detector_id, image=img, wait=0)
        motion_detection_manager.update_image_query_response(detector_id=detector_id, response=iq_response)


def _is_confident_enough(
    confidence: Optional[float], detector_metadata: Detector, confidence_threshold: Optional[float] = None
) -> bool:
    """
    Determine if an image query is confident enough to return.
    :param image_query: the image query to check
    :param detector_metadata: the detector's metadata
    :param confidence_threshold: the confidence threshold to use. If not set, use the detector's confidence threshold.
    :return: True if the image query is confident enough to return, False otherwise
    """
    if confidence is None:
        return True  # None confidence means answered by a human, so it's confident enough to return
    if confidence_threshold is not None:
        return confidence >= confidence_threshold
    return confidence >= detector_metadata.confidence_threshold
