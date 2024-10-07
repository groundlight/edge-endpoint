from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable

import groundlight
import ksuid
from fastapi import HTTPException, status
from model import (
    ROI,
    BinaryClassificationResult,
    CountingResult,
    CountModeConfiguration,
    ImageQuery,
    ImageQueryTypeEnum,
    Label,
    ModeEnum,
    MultiClassificationResult,
    MultiClassModeConfiguration,
    ResultTypeEnum,
    Source,
)
from PIL import Image

from . import constants


def create_iqe(  # noqa: PLR0913
    detector_id: str,
    mode: ModeEnum,
    mode_configuration: dict[str, Any] | None,
    result_value: int,
    confidence: float,
    confidence_threshold: float,
    query: str = "",
    patience_time: float = constants.DEFAULT_PATIENCE_TIME,
    rois: list[ROI] | None = None,
    text: str | None = None,
) -> ImageQuery:
    result_type, result = _mode_to_result_and_type(mode, mode_configuration, confidence, result_value)
    iq = ImageQuery(
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
    return iq


def _mode_to_result_and_type(
    mode: ModeEnum, mode_configuration: dict[str, Any] | None, confidence: float, result_value: int
):
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
        greater_than_max = result_value > max_count if max_count is not None else None
        result_type = ResultTypeEnum.counting
        result = CountingResult(
            confidence=confidence,
            source=source,
            count=result_value,
            greater_than_max=greater_than_max,
        )
    elif mode == ModeEnum.MULTI_CLASS:
        if mode_configuration is None:
            raise ValueError("mode_configuration for MultiClassification detector shouldn't be None.")
        multiclass_mode_configuration = MultiClassModeConfiguration(**mode_configuration)
        label = multiclass_mode_configuration.class_names[str(result_value)]
        result_type = ResultTypeEnum.multi_classification
        result = MultiClassificationResult(
            confidence=confidence,
            source=source,
            label=label,
        )
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
    except groundlight.NotFoundError as ex:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))
    except Exception as ex:
        if hasattr(ex, "status"):
            raise HTTPException(status_code=e.status, detail=str(ex)) from ex
        raise ex


def prefixed_ksuid(prefix: str = None) -> str:
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
