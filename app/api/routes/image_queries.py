import logging
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from groundlight import Groundlight
from model import (
    ImageQuery,
)
from PIL import Image

from app.core import constants
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


async def validate_query_params_for_edge(request: Request, invalid_edge_params: set):
    query_params = set(request.query_params.keys())
    invalid_provided_params = query_params.intersection(invalid_edge_params)
    if invalid_provided_params:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid query parameters for submit_image_query to edge-endpoint: {invalid_provided_params}",
        )


@router.post("", response_model=ImageQuery)
async def post_image_query(  # noqa: PLR0913, PLR0915, PLR0912
    request: Request,
    detector_id: str = Query(...),
    image: Image.Image = Depends(validate_image),
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

    TODO: fixup
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

    :param app_state: Application's state manager.
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
        return safe_call_sdk(
            gl.submit_image_query,
            detector=detector_id,
            image=image,
            wait=0,
            patience_time=patience_time,
            confidence_threshold=confidence_threshold,
            human_review=human_review,
            want_async=True,
        )

    edge_inference_manager = app_state.edge_inference_manager
    require_human_review = human_review == "ALWAYS"
    image_query: ImageQuery | None = None

    # Confirm the existence of the detector in GL, get relevant metadata
    detector_metadata = get_detector_metadata(detector_id=detector_id, gl=gl)  # NOTE: API call (once, then cached)

    if confidence_threshold is None:
        # Use detector's confidence threshold
        confidence_threshold: float = detector_metadata.confidence_threshold

    # -- Edge-model Inference --
    if not require_human_review and edge_inference_manager.inference_is_available(detector_id=detector_id):
        logger.debug(f"Local inference is available for {detector_id=}. Running inference...")
        results = edge_inference_manager.run_inference(detector_id=detector_id, image=image)
        confidence = results["confidence"]

        if (
            edge_only
            or edge_only_inference
            or _is_confident_enough(
                confidence=confidence,
                confidence_threshold=confidence_threshold,
            )
        ):
            if edge_only:
                logger.debug(
                    f"Edge-only mode enabled - will not escalate to cloud, regardless of confidence. {detector_id=}"
                )
            elif edge_only_inference:
                logger.debug(
                    "Edge-only inference mode is enabled on this detector. The edge model's answer will be "
                    "returned regardless of confidence, but will still be escalated to the cloud if the confidence "
                    "is not high enough. "
                    f"{detector_id=}"
                )
            else:
                logger.debug(f"Edge detector confidence is high enough to return. {detector_id=}")

            if patience_time is None:
                patience_time = constants.DEFAULT_PATIENCE_TIME

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
            app_state.db_manager.create_iqe_record(iq=image_query)

            if edge_only_inference and not _is_confident_enough(
                confidence=confidence,
                confidence_threshold=confidence_threshold,
            ):
                logger.info("Escalating to the cloud API server for future training due to low confidence.")
                background_tasks.add_task(safe_call_sdk, gl.ask_async, detector=detector_id, image=image)
        else:
            logger.info(
                f"Edge-inference is not confident, escalating to cloud. ({confidence} < thresh={confidence_threshold})"
            )

    # -- Edge-inference is not available --
    else:
        # Create an edge-inference deployment record, which may be used to spin up an edge-inference, if applicable.
        api_token = gl.api_client.configuration.api_key["ApiToken"]
        logger.debug(f"Local inference not available for {detector_id=}. Creating inference deployment record.")
        app_state.db_manager.create_inference_deployment_record(
            deployment={"detector_id": detector_id, "api_token": api_token, "deployment_created": False}
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
        image_query: ImageQuery = safe_call_sdk(
            gl.submit_image_query,
            detector=detector_id,
            image=image,
            wait=0,
            patience_time=patience_time,
            confidence_threshold=confidence_threshold,
            human_review=human_review,
        )
        # TODO: patch in the edge inference results if the cloud results are not confident enough?

    return image_query


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
