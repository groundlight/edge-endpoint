import logging
import random
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from groundlight import Groundlight
from model import ImageQuery

from app.core.app_state import (
    AppState,
    get_app_state,
    get_detector_metadata,
    get_groundlight_sdk_instance,
    refresh_detector_metadata_if_needed,
)
from app.core.edge_inference import get_edge_inference_model_name
from app.core.utils import HUMAN_REVIEW_TYPE, create_iq, safe_call_sdk, safe_escalate_iq
from app.metrics.iqactivity import record_iq_activity

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
    human_review: HUMAN_REVIEW_TYPE = Query(None),
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

    require_human_review = human_review == "ALWAYS"
    detector_inference_config = app_state.edge_inference_manager.detector_inference_configs.get(detector_id)
    return_edge_prediction = (
        detector_inference_config.always_return_edge_prediction if detector_inference_config is not None else False
    )
    disable_cloud_escalation = (
        detector_inference_config.disable_cloud_escalation if detector_inference_config is not None else False
    )

    if require_human_review and return_edge_prediction:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Human review cannot be required if edge predictions are required.",
        )

    record_iq_activity(detector_id)  # for metrics

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
    # Schedule a background task to refresh the detector metadata if it's too old
    background_tasks.add_task(refresh_detector_metadata_if_needed, detector_id, gl)

    confidence_threshold = confidence_threshold or detector_metadata.confidence_threshold

    # for holding edge results if and when available
    results = None

    if require_human_review:
        # If human review is required, we should skip edge inference completely
        logger.debug("Received human_review=ALWAYS. Skipping edge inference.")
    elif app_state.edge_inference_manager.inference_is_available(detector_id=detector_id):
        # -- Edge-model Inference --
        logger.debug(f"Local inference is available for {detector_id=}. Running inference...")
        results = await app_state.edge_inference_manager.run_inference(
            detector_id=detector_id, image_bytes=image_bytes, content_type=content_type
        )
        ml_confidence = results["confidence"]

        is_confident_enough = ml_confidence >= confidence_threshold
        if return_edge_prediction or is_confident_enough:  # Return the edge prediction
            if return_edge_prediction:
                logger.debug(f"Returning edge prediction without cloud escalation. {detector_id=}")
            else:
                logger.debug(f"Edge detector confidence sufficient. {detector_id=}")

            image_query = create_iq(
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

            # Skip cloud operations if escalation is disabled
            if disable_cloud_escalation:
                return image_query

            if is_confident_enough:  # Audit confident edge predictions at the specified rate
                if random.random() < app_state.edge_config.global_config.confident_audit_rate:
                    logger.debug(
                        f"Auditing confident edge prediction with confidence {ml_confidence} for detector {detector_id=}."
                    )
                    background_tasks.add_task(
                        safe_call_sdk,
                        gl.submit_image_query,
                        detector=detector_id,
                        image=image_bytes,
                        wait=0,
                        patience_time=patience_time,
                        confidence_threshold=confidence_threshold,
                        want_async=True,
                        metadata={
                            "is_edge_audit": True,  # This metadata will trigger an audit in the cloud
                            "edge_result": results,
                        },
                        image_query_id=image_query.id,  # We give the cloud IQ the same ID as the returned edge IQ
                    )

                    # Don't want to escalate to cloud again if we're already auditing the query
                    return image_query

            # Escalate after returning edge prediction if escalation is enabled and we have low confidence.
            if not is_confident_enough:
                # Only escalate if we haven't escalated on this detector too recently.
                if app_state.edge_inference_manager.escalation_cooldown_complete(detector_id=detector_id):
                    logger.debug(
                        f"Escalating to cloud due to low confidence: {ml_confidence} < thresh={confidence_threshold}"
                    )
                    background_tasks.add_task(
                        safe_call_sdk,
                        gl.submit_image_query,  # This has to be submit_image_query in order to specify image_query_id
                        detector=detector_id,
                        image=image_bytes,
                        wait=0,
                        patience_time=patience_time,
                        confidence_threshold=confidence_threshold,
                        human_review=human_review,
                        want_async=True,
                        metadata={"edge_result": results},
                        image_query_id=image_query.id,  # Ensure the cloud IQ has the same ID as the returned edge IQ
                    )
                else:
                    logger.debug(
                        f"Not escalating to cloud due to rate limit on background cloud escalations: {detector_id=}"
                    )

            return image_query
    else:
        # -- Edge-inference is not available --
        # Create an edge-inference deployment record, which may be used to spin up an edge-inference server.
        logger.debug(f"Local inference not available for {detector_id=}. Creating inference deployment record.")
        api_token = gl.api_client.configuration.api_key["ApiToken"]
        primary_model_name = get_edge_inference_model_name(detector_id=detector_id, is_oodd=False)
        oodd_model_name = get_edge_inference_model_name(detector_id=detector_id, is_oodd=True)

        app_state.db_manager.create_or_update_inference_deployment_record(
            deployment={
                "model_name": primary_model_name,
                "detector_id": detector_id,
                "api_token": api_token,
                "deployment_created": False,
            }
        )
        app_state.db_manager.create_or_update_inference_deployment_record(
            deployment={
                "model_name": oodd_model_name,
                "detector_id": detector_id,
                "api_token": api_token,
                "deployment_created": False,
            }
        )

        if return_edge_prediction:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Edge predictions are required, but an edge-inference server is not available for {detector_id=}."
                ),
            )

    # Fall back to submitting the image to the cloud
    if disable_cloud_escalation:
        raise AssertionError("Cloud escalation is disabled.")  # ...should never reach this point

    logger.debug(f"Submitting image query to cloud for {detector_id=}")
    # return safe_call_sdk(
    #     gl.submit_image_query,
    #     detector=detector_id,
    #     image=image_bytes,
    #     wait=5,  # wait on the client, not here
    #     patience_time=patience_time,
    #     confidence_threshold=confidence_threshold,
    #     human_review=human_review,
    #     metadata={"edge_result": results},
    #     want_async=True,
    # )
    return safe_escalate_iq(
        gl=gl,
        results=results,
        detector_id=detector_id,
        image_bytes=image_bytes,
        patience_time=patience_time,
        confidence_threshold=confidence_threshold,
        human_review=human_review,
        query=detector_metadata.query,
        mode=detector_metadata.mode,
    )
