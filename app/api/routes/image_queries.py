import logging
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from groundlight import Groundlight, ModeEnum
from model import ImageQuery

from app.core.app_state import (
    AppState,
    get_app_state,
    get_groundlight_sdk_instance,
)
from app.core.utils import create_iq
from app.metrics.iq_activity import record_activity_for_metrics

logger = logging.getLogger(__name__)

router = APIRouter()


async def validate_content_type(request: Request) -> str:
    if not request.headers.get("Content-Type", "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Request body must be image bytes"
        )
    return request.headers.get("Content-Type", "")


async def validate_image_bytes(request: Request, content_type: str = Depends(validate_content_type)) -> bytes:
    image_bytes = await request.body()
    return image_bytes


async def validate_query_params_for_edge(request: Request):
    invalid_edge_params = {
        "inspection_id",  # inspection_id will not be supported on the edge
        "metadata",  # metadata is not supported on the edge currently, we need to set up persistent storage first
        "image_query_id",  # specifying an image query ID will not be supported on the edge
    }
    query_params = set(request.query_params.keys())
    invalid_provided_params = query_params.intersection(invalid_edge_params)
    if invalid_provided_params:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid query parameters: {invalid_provided_params}"
        )


@router.post("", response_model=ImageQuery)
async def post_image_query(  # noqa: PLR0913, PLR0915, PLR0912
    request: Request,
    background_tasks: BackgroundTasks,
    detector_id: str = Query(...),
    content_type: str = Depends(validate_content_type),
    image_bytes: bytes = Depends(validate_image_bytes),
    patience_time: Optional[float] = Query(None, ge=0),
    confidence_threshold: Optional[float] = Query(None, ge=0, le=1),
    human_review: Optional[Literal["DEFAULT", "ALWAYS", "NEVER"]] = Query(None),
    want_async: bool = Query(False),
    gl: Groundlight = Depends(get_groundlight_sdk_instance),
    app_state: AppState = Depends(get_app_state),
):
    """
    MODIFIED TO ONLY SUPPORT EDGE INFERENCE

    Submit an image query for a given detector.

    This function attempts to run inference locally on the edge, if possible,
    before potentially escalating to the cloud.

    Args:
        detector_id (str): The unique identifier of the detector to use, e.g., 'det_12345'.
        content_type (str): The content type of the image, e.g., 'image/jpeg'.
        image_bytes (bytes): The raw binary data of the image.
        patience_time (Optional[float]): Maximum time (in seconds) to wait for a confident answer.
            Longer patience times increase the likelihood of obtaining a confident answer.
            During this period, Groundlight may update ML predictions and prioritize human review if necessary.
            This is a soft server-side timeout. If not set, the detector's default patience time is used.
        confidence_threshold (Optional[float]): The minimum confidence level required for an answer.
            If not set, the detector's default confidence threshold is used.
        human_review (Optional[Literal["DEFAULT", "ALWAYS", "NEVER"]]):
            - "DEFAULT" or None: Send for human review only if the ML prediction is not confident.
            - "ALWAYS": Always send for human review.
            - "NEVER": Never send for human review.
        want_async (bool): If True, returns immediately after query submission without waiting for a prediction.
            The returned ImageQuery will have a 'result' of None. Requires 'wait' to be set to 0.

    Dependencies:
        gl (Groundlight): Application's Groundlight SDK instance.
        app_state (AppState): Application's state manager.
        background_tasks (BackgroundTasks): FastAPI background tasks manager for asynchronous operations.

    Returns:
        ImageQuery: The submitted image query, potentially with results depending on the mode of operation.

    Raises:
        HTTPException: If there are issues with the request parameters or processing.
    """

    await validate_query_params_for_edge(request)

    require_human_review = False
    return_edge_prediction = True

    if require_human_review and return_edge_prediction:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Human review cannot be required if edge predictions are required.",
        )

    record_activity_for_metrics(detector_id, activity_type="iqs")

    if want_async:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Async requests are not supported on edge-only mode.",
        )

    confidence_threshold = 0.9  # Set an arbitrary value since we cannot get one from the cloud.

    # for holding edge results if and when available
    results = None

    if app_state.edge_inference_manager.inference_is_available(detector_id=detector_id):
        # -- Edge-model Inference --
        logger.debug(f"Local inference is available for {detector_id=}. Running inference...")
        results = app_state.edge_inference_manager.run_inference(
            detector_id=detector_id, image_bytes=image_bytes, content_type=content_type
        )
        ml_confidence = results["confidence"]

        return create_iq(
            detector_id=detector_id,
            mode=ModeEnum.BINARY,  # URCap only supports binary
            mode_configuration=None,  # None works for binary detectors
            result_value=results["label"],
            confidence=ml_confidence,
            confidence_threshold=confidence_threshold,
            is_done_processing=True,
            query="",  # We cannot fetch this, but do we really need it?
            patience_time=patience_time,
            rois=results["rois"],
            text=results["text"],
        )
        is_confident_enough = ml_confidence >= confidence_threshold
        if return_edge_prediction or is_confident_enough:  # Return the edge prediction
            if return_edge_prediction:
                logger.debug(f"Returning edge prediction without cloud escalation. {detector_id=}")
            else:
                logger.debug(f"Edge detector confidence sufficient. {detector_id=}")

            create_iq(
                detector_id=detector_id,
                mode=ModeEnum.BINARY,  # URCap only supports binary
                mode_configuration=None,  # None works for binary detectors
                result_value=results["label"],
                confidence=ml_confidence,
                confidence_threshold=confidence_threshold,
                is_done_processing=True,
                query="",  # We cannot fetch this, but do we really need it?
                patience_time=patience_time,
                rois=results["rois"],
                text=results["text"],
            )

    else:
        # -- Edge-inference is not available --
        if return_edge_prediction:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Edge predictions are required, but an edge-inference server is not available for {detector_id=}."
                ),
            )
