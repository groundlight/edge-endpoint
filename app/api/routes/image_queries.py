import logging
from io import BytesIO
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from groundlight import Groundlight
from model import (
    ImageQuery,
)
from PIL import Image

from app.core.app_state import (
    AppState,
    get_app_state,
    get_detector_metadata,
    get_groundlight_sdk_instance,
)
from app.core.utils import create_iqe, safe_call_sdk

logger = logging.getLogger(__name__)

router = APIRouter()


async def validate_image(request: Request) -> Image.Image:
    """
    Validate the image file contained in the request body and return a PIL Image object.
    :param file: The uploaded image file to be validated.
    :return: A PIL Image object if the file is a valid image.
    :raises HTTPException: If the file is not an image or cannot be processed.
    """
    if not request.headers.get("Content-Type", "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Request body must be image bytes"
        )

    image_bytes = await request.body()
    try:
        # Attempt to open the image
        image = Image.open(BytesIO(image_bytes))

        # Image.open() does not fully process the image data. It's possible for Image.open()
        # to succeed but then fail when the image data is actually being processed.
        # To ensure that the image can be fully processed, we call img.load() to force loading
        # the entire image. If this fails, we know that the image is invalid.
        image.load()
    except IOError as ex:
        logger.error("Failed to load image", exc_info=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid input image") from ex
    return image


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
    image: Image.Image = Depends(validate_image),
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
        image (Image.Image): The image to submit.
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
    detector_config = app_state.edge_config.detectors.get(detector_id)
    edge_only = detector_config.edge_only if detector_config is not None else False
    edge_only_inference = detector_config.edge_only_inference if detector_config is not None else False
    is_edge_only = edge_only or edge_only_inference

    # Early return for async requests in non-edge-only mode
    if want_async and not is_edge_only:
        logger.debug(f"Submitting ask_async image query to cloud API server for {detector_id=}")
        return safe_call_sdk(
            gl.ask_async,
            detector=detector_id,
            image=image,
            patience_time=patience_time,
            confidence_threshold=confidence_threshold,
            human_review=human_review,
        )

    edge_inference_manager = app_state.edge_inference_manager
    require_human_review = human_review == "ALWAYS"

    # Confirm the existence of the detector in GL, get relevant metadata
    detector_metadata = get_detector_metadata(detector_id=detector_id, gl=gl)  # NOTE: API call (once, then cached)
    confidence_threshold = confidence_threshold or detector_metadata.confidence_threshold

    # -- Edge-model Inference --
    if not require_human_review and edge_inference_manager.inference_is_available(detector_id=detector_id):
        logger.debug(f"Local inference is available for {detector_id=}. Running inference...")
        results = edge_inference_manager.run_inference(detector_id=detector_id, image=image)
        confidence = results["confidence"]

        if is_edge_only or _is_confident_enough(confidence=confidence, confidence_threshold=confidence_threshold):
            if edge_only:
                logger.debug(f"Edge-only mode: no cloud escalation. {detector_id=}")
            elif edge_only_inference:
                logger.debug(f"Edge-only inference: may escalate to cloud to aid training. {detector_id=}")
            else:
                logger.debug(f"Edge detector confidence sufficient. {detector_id=}")

            image_query = create_iqe(
                detector_id=detector_id,
                mode=detector_metadata.mode,
                mode_configuration=detector_metadata.mode_configuration,
                result_value=results["label"],
                confidence=confidence,
                confidence_threshold=confidence_threshold,
                query=detector_metadata.query,
                patience_time=patience_time,
                rois=results["rois"],
                text=results["text"],
            )
            background_tasks.add_task(app_state.db_manager.create_iqe_record, iq=image_query)

            if edge_only_inference and not _is_confident_enough(
                confidence=confidence,
                confidence_threshold=confidence_threshold,
            ):
                logger.debug("Escalating to the cloud API server for future training due to low confidence.")
                background_tasks.add_task(
                    safe_call_sdk,
                    gl.ask_async,
                    detector=detector_id,
                    image=image,
                    patience_time=patience_time,
                    confidence_threshold=confidence_threshold,
                    human_review=human_review,
                )

            return image_query

        logger.debug(f"Escalating to cloud due to low confidence: {confidence} < thresh={confidence_threshold}")

    # -- Edge-inference is not available --
    else:
        # Create an edge-inference deployment record, which may be used to spin up an edge-inference, if applicable.
        api_token = gl.api_client.configuration.api_key["ApiToken"]
        logger.debug(f"Local inference not available for {detector_id=}. Creating inference deployment record.")
        app_state.db_manager.create_inference_deployment_record(
            deployment={"detector_id": detector_id, "api_token": api_token, "deployment_created": False}
        )

        # Fail if edge inference is not available and edge-only mode is enabled
        if is_edge_only:
            mode = "Edge-only mode" if edge_only else "Edge-only inference mode"
            raise RuntimeError(f"{mode} is enabled, but edge inference is not available.")

    # Finally, fall back to submitting the image to the cloud
    # NOTE: Waiting is done on the customer's client, not here. Otherwise we would be blocking the
    # response to the customer's client from the edge-endpoint for many seconds. This has the side
    # effect of not allowing customers to set patience_time on a per-iq basis when using the edge-endpoint.
    # TODO: patch in the edge inference results if the cloud results are not confident enough?
    logger.debug(f"Submitting image query to cloud for {detector_id=}")
    return safe_call_sdk(
        gl.submit_image_query,
        detector=detector_id,
        image=image,
        wait=0,
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


def _is_confident_enough(confidence: Optional[float], confidence_threshold: float) -> bool:
    """
    Determine if an image query is confident enough to return.
    :param image_query: the image query to check
    :param confidence_threshold: the confidence threshold to use. If not set, use the detector's confidence threshold.
    :return: True if the image query is confident enough to return, False otherwise
    """
    if confidence is None:
        return True  # None confidence means answered by a human, so it's confident enough to return
    return confidence >= confidence_threshold
