from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable

import cachetools
import ksuid
from fastapi import HTTPException
from model import (
    ROI,
    BinaryClassificationResult,
    CountingResult,
    CountModeConfiguration,
    ImageQuery,
    ImageQueryTypeEnum,
    Label,
    ModeEnum,
    ResultTypeEnum,
    Source,
)
from PIL import Image
from pydantic import BaseModel, ValidationError

from app.core import constants


def create_iq(  # noqa: PLR0913
    detector_id: str,
    mode: ModeEnum,
    mode_configuration: dict[str, Any] | None,
    result_value: int,
    confidence: float,
    confidence_threshold: float,
    is_done_processing: bool,
    query: str = "",
    patience_time: float | None = None,
    rois: list[ROI] | None = None,
    text: str | None = None,
) -> ImageQuery:
    """
    Creates an ImageQuery object for the appropriate detector with the given result.

    :param mode: The mode of the detector.
    :param mode_configuration: A dict version of the config for the mode. None for binary detectors.
    :param result_value: The predicted value.
    :param confidence: The confidence of the predicted value.
    :param confidence_threshold: The confidence threshold for the query.
    :param is_done_processing: Whether this is the final answer for the query.
    :param query: The query string.
    :param patience_time: The acceptable time to wait for a result.
    :param rois: The ROIs associated with the prediction, if applicable.
    :param text: The text associated with the prediction, if applicable.

    :return: The created ImageQuery.
    """
    if patience_time is None:
        patience_time = constants.DEFAULT_PATIENCE_TIME
    result_type, result = _mode_to_result_and_type(mode, mode_configuration, confidence, result_value)

    return ImageQuery(
        metadata={"is_from_edge": True},
        id=prefixed_ksuid(prefix="iq_"),
        type=ImageQueryTypeEnum.image_query,
        created_at=datetime.now(timezone.utc),
        query=query,
        detector_id=detector_id,
        result_type=result_type,
        result=result,
        patience_time=patience_time,
        confidence_threshold=confidence_threshold,
        rois=rois,
        text=text,
        done_processing=is_done_processing,
    )


def _mode_to_result_and_type(
    mode: ModeEnum, mode_configuration: dict[str, Any] | None, confidence: float, result_value: int
) -> tuple[ResultTypeEnum, BinaryClassificationResult | CountingResult]:
    """
    Maps the detector mode to the corresponding result type and generates the result object
    based on the provided mode, confidence, and result value.

    :param mode: The mode of the detector.
    :param mode_configuration:
    :param confidence: The confidence of the predicted value.
    :param result_value: The predicted value.

    :return: A tuple of the result type and the generated result object.
    """
    source = Source.EDGE  # Source is always EDGE for edge model results
    if mode == ModeEnum.BINARY:
        result_type = ResultTypeEnum.binary_classification
        label = Label.NO if result_value else Label.YES  # Map false / 0 to "YES" and true / 1 to "NO"
        result = BinaryClassificationResult(
            confidence=confidence,
            source=source,
            label=label,
        )
    elif mode == ModeEnum.COUNT:
        if mode_configuration is None:
            raise ValueError("mode_configuration for Counting detector shouldn't be None.")
        count_mode_configuration = CountModeConfiguration(**mode_configuration)
        max_count = count_mode_configuration.max_count
        greater_than_max = False
        if max_count is not None:
            greater_than_max = result_value > max_count
            result_value = max_count if greater_than_max else result_value
        result_type = ResultTypeEnum.counting
        result = CountingResult(
            confidence=confidence,
            source=source,
            count=result_value,
            greater_than_max=greater_than_max,
        )
    elif mode == ModeEnum.MULTI_CLASS:
        raise NotImplementedError("Multiclass functionality is not yet implemented for the edge endpoint.")
        # TODO add support for multiclass functionality.
    else:
        raise ValueError(f"Got unrecognized or unsupported detector mode: {mode}")

    return result_type, result


def safe_call_sdk(api_method: Callable, **kwargs):
    """
    This ensures that we correctly handle HTTP error status codes. In some cases,
    for instance, 400 error codes from the SDK are forwarded as 500 by FastAPI,
    which is not what we want.
    """
    try:
        return api_method(**kwargs)
    # except groundlight.NotFoundError as ex:
    #     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))
    except Exception as ex:
        if hasattr(ex, "status"):
            raise HTTPException(status_code=ex.status, detail=str(ex)) from ex
        raise ex


def prefixed_ksuid(prefix: str | None = None) -> str:
    """Returns a unique identifier, with a bunch of nice properties.
    It's statistically guaranteed unique, about as strongly as UUIDv4 are.
    They're sortable by time, approximately, assuming your clocks are sync'd properly.
    They are a single text token, without any hyphens, so you can double-click to select them
    and not worry about your log-search engine (ElasticSearch etc) tokenizing them into parts.
    They can include a semantic prefix such as "chk_" to help identify them.
    They're base62 encoded, so no funny characters, but denser than hex coding of UUID.

    This is just a prefixed KSUID, which is cool.
    """
    if prefix:
        if not prefix.endswith("_"):
            prefix = f"{prefix}_"
    else:
        prefix = ""
    # the "ms" version adds millisecond-level time resolution, at the cost of a equivalent bits of random.
    # Actual collisions remain vanishingly unlikely, and the database would block them if they did happen.
    # But having millisecond resolution is useful in that it means multiple IDs generated during
    # the same request will get ordered properly.
    k = ksuid.KsuidMs()
    out = f"{prefix}{k}"
    return out


def pil_image_to_bytes(img: Image.Image, format: str = "JPEG") -> bytes:
    """
    Convert a PIL Image object to JPEG bytes.

    Args:
        img (Image.Image): The PIL Image object.
        format (str, optional): The image format. Defaults to "JPEG".

    Returns:
        bytes: The raw bytes of the image.
    """
    with BytesIO() as buffer:
        img.save(buffer, format=format)
        return buffer.getvalue()


class TimestampedTTLCache(cachetools.TTLCache):
    """TTLCache subclass that tracks when items were added to the cache."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamps = {}  # Store timestamps for each key

    def __setitem__(self, key, value, cache_setitem=cachetools.Cache.__setitem__):
        # Track the current time when setting an item
        self.timestamps[key] = self.timer()
        super().__setitem__(key, value, cache_setitem)

    def __delitem__(self, key, cache_delitem=cachetools.Cache.__delitem__):
        super().__delitem__(key, cache_delitem)
        self.timestamps.pop(key, None)

    def get_timestamp(self, key) -> float | None:
        """Get the timestamp when an item was added to the cache."""
        return self.timestamps.get(key)


# Utilities for parsing the fetch models response
class ModelInfoBase(BaseModel):
    """Both types of model info responses will contain this information."""

    pipeline_config: str
    predictor_metadata: str


class ModelInfoNoBinary(ModelInfoBase):
    """
    If the detector's edge pipeline has no trained model binary, this will be the response.
    The inference server will create a zero-shot pipeline from the pipeline config.
    """

    pass


class ModelInfoWithBinary(ModelInfoBase):
    """
    If the detector's edge pipeline has a trained model binary, this will be the response.
    The inference server will load the model binary.
    """

    model_binary_id: str
    model_binary_url: str

    class Config:
        protected_namespaces = ()  # Disables protection for all namespaces, since model_ is protected by default


def parse_model_info(
    fetch_model_response: dict[str, str],
) -> tuple[ModelInfoBase, ModelInfoBase]:
    """
    Parse the response from the fetch model urls endpoint. Attempt to parse both the edge and oodd models
    with their ML binaries, and fall back to no binary cases if that fails.
    """
    # The ModelInfo fields are named correspondingly to the response keys for the edge model, so we can use the
    # pydantic model to validate and parse the response. The OODD keys will be ignored, since they aren't in the
    # model fields
    try:
        edge_model_info = ModelInfoWithBinary(**fetch_model_response)
    except ValidationError:
        edge_model_info = ModelInfoNoBinary(**fetch_model_response)

    try:
        oodd_model_info = ModelInfoWithBinary(
            model_binary_id=fetch_model_response["oodd_model_binary_id"],
            model_binary_url=fetch_model_response["oodd_model_binary_url"],
            pipeline_config=fetch_model_response["oodd_pipeline_config"],
            predictor_metadata=fetch_model_response["predictor_metadata"],
        )
    except (ValidationError, KeyError):
        oodd_model_info = ModelInfoNoBinary(
            pipeline_config=fetch_model_response["oodd_pipeline_config"],
            predictor_metadata=fetch_model_response["predictor_metadata"],
        )

    return edge_model_info, oodd_model_info
