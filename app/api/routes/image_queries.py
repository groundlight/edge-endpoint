import logging
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from groundlight import Groundlight
from model import (
    ImageQuery,
)

from app.core.app_state import (
    AppState,
    get_app_state,
    get_detector_metadata,
    get_groundlight_sdk_instance,
)
from app.core.utils import create_iqe, safe_call_sdk

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
    Submit an image query for a given detector.

    This function attempts to run inference locally on the edge, if possible,
    before potentially escalating to the cloud.

    Args:
        detector_id (str): The unique identifier of the detector to use, e.g., 'det_12345'.
        image_bytes (bytes): The raw binary data of the image to be analyzed.
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

    require_human_review = human_review == "ALWAYS"
    detector_config = app_state.edge_config.detectors.get(detector_id)
    return_edge_prediction = detector_config.always_return_edge_prediction if detector_config is not None else False
    disable_cloud_escalation = detector_config.disable_cloud_escalation if detector_config is not None else False

    if require_human_review and return_edge_prediction:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Human review cannot be required if edge predictions are required.",
        )

    if want_async:  # just submit to the cloud w/ ask_async
        if return_edge_prediction:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Async requests are not supported when 'always_return_edge_prediction' is set to True.",
            )
        logger.debug(f"Submitting ask_async image query to cloud API server for {detector_id=}")
        return safe_call_sdk(
            gl.ask_async,
            detector=detector_id,
            image=image_bytes,
            patience_time=patience_time,
            confidence_threshold=confidence_threshold,
            human_review=human_review,
        )

    # Confirm the existence of the detector in GL, get relevant metadata
    detector_metadata = get_detector_metadata(detector_id=detector_id, gl=gl)  # NOTE: API call (once, then cached)
    confidence_threshold = confidence_threshold or detector_metadata.confidence_threshold

    # -- Edge-model Inference --
    if app_state.edge_inference_manager.inference_is_available(detector_id=detector_id):
        logger.debug(f"Local inference is available for {detector_id=}. Running inference...")
        results = app_state.edge_inference_manager.run_inference(
            detector_id=detector_id, image_bytes=image_bytes, content_type=content_type
        )
        ml_confidence = results["confidence"]

        is_confident_enough = ml_confidence >= confidence_threshold
        if return_edge_prediction or is_confident_enough:  # return the edge prediction
            if return_edge_prediction:
                logger.debug(f"Returning edge prediction without cloud escalation. {detector_id=}")
            else:
                logger.debug(f"Edge detector confidence sufficient. {detector_id=}")

            image_query = create_iqe(
                detector_id=detector_id,
                mode=detector_metadata.mode,
                mode_configuration=detector_metadata.mode_configuration,
                result_value=results["label"],
                confidence=ml_confidence,
                confidence_threshold=confidence_threshold,
                query=detector_metadata.query,
                patience_time=patience_time,
                rois=results["rois"],
                text=results["text"],
            )
            app_state.db_manager.create_iqe_record(image_query)

            if not disable_cloud_escalation and not is_confident_enough:  # escalate after returning edge prediction
                logger.debug(
                    f"Escalating to cloud due to low confidence: {ml_confidence} < thresh={confidence_threshold}"
                )
                background_tasks.add_task(
                    safe_call_sdk,
                    gl.ask_async,
                    detector=detector_id,
                    image=image_bytes,
                    patience_time=patience_time,
                    confidence_threshold=confidence_threshold,
                    human_review=human_review,
                )

            return image_query

    # -- Edge-inference is not available --
    else:
        # Create an edge-inference deployment record, which may be used to spin up an edge-inference server.
        logger.debug(f"Local inference not available for {detector_id=}. Creating inference deployment record.")
        api_token = gl.api_client.configuration.api_key["ApiToken"]
        app_state.db_manager.create_or_update_inference_deployment_record(
            deployment={"detector_id": detector_id, "api_token": api_token, "deployment_created": False}
        )

        if return_edge_prediction:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Edge predictions are required, but an edge-inference server is not available for {detector_id=}."
                ),
            )

    # Finally, fall back to submitting the image to the cloud
    if disable_cloud_escalation:
        raise AssertionError("Cloud escalation is disabled.")  # ...should never reach this point

    logger.debug(f"Submitting image query to cloud for {detector_id=}")
    return safe_call_sdk(
        gl.submit_image_query,
        detector=detector_id,
        image=image_bytes,
        wait=0,  # wait on the client, not here
        patience_time=patience_time,
        confidence_threshold=confidence_threshold,
        human_review=human_review,
    )


@router.get("/{id}", response_model=ImageQuery)
async def get_image_query(
    id: str, gl: Groundlight = Depends(get_groundlight_sdk_instance), app_state: AppState = Depends(get_app_state)
):
    if id.startswith("iqe_"):
        image_query = app_state.db_manager.get_iqe_record(image_query_id=id)
        if not image_query:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Image query with ID {id} not found")
        return image_query
    return safe_call_sdk(gl.get_image_query, id=id)
