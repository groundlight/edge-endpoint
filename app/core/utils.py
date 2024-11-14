from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable

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


def create_iqe(  # noqa: PLR0913
    detector_id: str,
    mode: ModeEnum,
    mode_configuration: dict[str, Any] | None,
    result_value: int,
    confidence: float,
    confidence_threshold: float,
    query: str = "",
    patience_time: float | None = None,
    rois: list[ROI] | None = None,
    text: str | None = None,
) -> ImageQuery:
    if patience_time is None:
        patience_time = constants.DEFAULT_PATIENCE_TIME
    result_type, result = _mode_to_result_and_type(mode, mode_configuration, confidence, result_value)

    return ImageQuery(
        metadata=None,
        id=prefixed_ksuid(prefix="iqe_"),
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
    )


def _mode_to_result_and_type(
    mode: ModeEnum, mode_configuration: dict[str, Any] | None, confidence: float, result_value: int
) -> tuple[ResultTypeEnum, BinaryClassificationResult | CountingResult]:
    """
    Maps the detector mode to the corresponding result type and generates the result object
    based on the provided mode, confidence, and result value.

    :param mode: The mode of the detector.
    :param confidence: The confidence of the predicted value.
    :param result_value: The predicted value.
    """
    source = Source.ALGORITHM  # Results from edge model are always from algorithm
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


# Function to parse the response
def parse_model_info(
    fetch_model_response: dict[str, str],
) -> ModelInfoNoBinary | ModelInfoWithBinary:
    try:
        # Attempt to parse as FetchModelResponseWithMLBinary
        return ModelInfoWithBinary(**fetch_model_response)
    except ValidationError:
        # Fall back to FetchModelResponseNoMLBinary
        return ModelInfoNoBinary(**fetch_model_response)
