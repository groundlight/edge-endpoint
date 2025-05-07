import json
import logging
import socket
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable

import cachetools
import ksuid
from cachetools import TTLCache, cached
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
    ResultTypeEnum,
    Source,
)
from PIL import Image
from pydantic import BaseModel, ValidationError

from app.core import constants
from app.core.constants import (
    CONNECTION_STATUS_TTL_SECS,
    CONNECTION_TEST_HOST,
    CONNECTION_TEST_PORT,
    CONNECTION_TIMEOUT,
    DEFAULT_POLLING_EXPONENTIAL_BACKOFF,
    DEFAULT_POLLING_INITIAL_DELAY,
    DEFAULT_POLLING_TIMEOUT_SEC,
)

logger = logging.getLogger(__name__)

METADATA_SIZE_LIMIT_BYTES = (
    1024  # This is defined in the SDK and will need to be manually updated here if it gets modified
)


def create_iq(  # noqa: PLR0913
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
    """
    Creates an ImageQuery object for the appropriate detector with the given result.

    :param mode: The mode of the detector.
    :param mode_configuration: A dict version of the config for the mode. None for binary detectors.
    :param result_value: The predicted value.
    :param confidence: The confidence of the predicted value.
    :param confidence_threshold: The confidence threshold for the query.
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


def get_formatted_timestamp_str() -> str:
    """Get the current datetime with the highest time precision available."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


connection_ttl_cache = TTLCache(maxsize=1, ttl=CONNECTION_STATUS_TTL_SECS)


@cached(connection_ttl_cache)
def is_connected() -> bool:
    """Check if the system can establish a network connection to the test host. Result is cached for a short time."""
    try:
        socket.setdefaulttimeout(CONNECTION_TIMEOUT)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((CONNECTION_TEST_HOST, CONNECTION_TEST_PORT))
        return True
    except socket.error:
        return False


def wait_with_exponential_backoff(
    condition: Callable,
    initial_delay: float = DEFAULT_POLLING_INITIAL_DELAY,
    exponential_backoff: float = DEFAULT_POLLING_EXPONENTIAL_BACKOFF,
    timeout_sec: float = DEFAULT_POLLING_TIMEOUT_SEC,
) -> bool:
    """
    Wait for the condition to be True, or the timeout_sec to be reached, with configurable exponential backoff.
    Returns True if the condition is met within the timeout_sec and False otherwise.
    """
    start_time = time.time()
    next_delay = initial_delay
    target_delay = 0.0
    while True:
        patience_so_far = time.time() - start_time
        if condition():
            return True
        if patience_so_far >= timeout_sec:
            return False
        target_delay = min(patience_so_far + next_delay, timeout_sec)
        sleep_time = max(target_delay - patience_so_far, 0)
        time.sleep(sleep_time)
        next_delay *= exponential_backoff


def wait_for_connection(
    timeout_sec: float = DEFAULT_POLLING_TIMEOUT_SEC,
) -> bool:
    """
    Wait for connection with configurable timeout and exponential backoff.
    Returns True if connection is achieved within the timeout_sec and False otherwise.
    """
    return wait_with_exponential_backoff(is_connected, timeout_sec=timeout_sec)


def safe_call_sdk(api_method: Callable, **kwargs):
    """
    This ensures that we correctly handle HTTP error status codes. In some cases,
    for instance, 400 error codes from the SDK are forwarded as 500 by FastAPI,
    which is not what we want.
    """
    # TODO do we want to do this waiting for connection here?
    has_connection = wait_for_connection(timeout_sec=1.0)  # Wait for connection, but only for one second
    if has_connection:
        try:
            return api_method(**kwargs)
        # except groundlight.NotFoundError as ex:
        #     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ex))
        except Exception as ex:
            if hasattr(ex, "status"):
                raise HTTPException(status_code=ex.status, detail=str(ex)) from ex
            raise ex

    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No internet connection available.")


def _size_of_dict_in_bytes(data: dict[str, Any]) -> int:
    """Returns the size, in # of bytes (assuming all ASCII characters), of the provided dict."""
    data_json = json.dumps(data)
    return len(data_json)


def _size_of_dict_with_field_in_bytes(initial_dict: dict[str, Any], new_data_key: str, new_data_value: Any) -> int:
    """
    Returns the size, in # of bytes (assuming all ASCII characters), of the provided dict if it included the provided
    key/value pair.
    """
    combined_dict = initial_dict.copy()
    combined_dict[new_data_key] = new_data_value
    return _size_of_dict_in_bytes(combined_dict)


def generate_metadata_dict(results: dict[str, Any] | None, is_edge_audit: bool = False) -> dict[str, Any]:
    """
    Generates the metadata for an IQ being escalated to the cloud.
    Includes `"is_edge_audit": True` if it is an edge audit.
    Includes `"edge_result": results` if including the results would not push the metadata over the size limit. If they
        would, includes the results without the ROIs if the resulting metadata does not exceed the limit.
    """
    metadata_dict = {}

    if is_edge_audit:
        metadata_dict["is_edge_audit"] = True  # This metadata will trigger an audit in the cloud

    metadata_with_results_size = _size_of_dict_with_field_in_bytes(metadata_dict, "edge_result", results)
    if metadata_with_results_size > METADATA_SIZE_LIMIT_BYTES:
        logger.debug(
            f"Inference results were {metadata_with_results_size} bytes, which made the metadata larger than the max "
            f"allowed size of {METADATA_SIZE_LIMIT_BYTES} bytes. Attempting to remove the ROIs from the results."
        )
        results_without_rois = results.copy()
        if "rois" in results_without_rois:
            results_without_rois["rois"] = f"{len(results['rois'])} ROIs were detected."
            metadata_with_results_size = _size_of_dict_with_field_in_bytes(
                metadata_dict, "edge_result", results_without_rois
            )
            if metadata_with_results_size <= METADATA_SIZE_LIMIT_BYTES:
                metadata_dict["edge_result"] = results_without_rois
            else:
                logger.debug(
                    "Inference results were still too large after removing ROIs. Not including the results in the "
                    "metadata."
                )
    else:
        metadata_dict["edge_result"] = results

    return metadata_dict


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


class TimestampedCache(cachetools.Cache):
    """Cache subclass that tracks when items were added to the cache, and supports suspending and restoring values."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timestamps: dict[Any, float] = {}  # Store timestamps for each key
        self._suspended_values: dict[Any, Any] = {}
        self._suspended_timestamps: dict[Any, float] = {}

    def __setitem__(self, key, value, timestamp: float | None = None):
        """Overrides the __setitem__ method to track the timestamp of when an item was added to the cache."""
        # Track the time when setting an item. If no timestamp is provided, use the current time.
        if timestamp is None:
            timestamp = time.monotonic()
        self._timestamps[key] = timestamp
        super().__setitem__(key, value)

    def __delitem__(self, key):
        """Overrides the __delitem__ method to remove the timestamp of when an item was added to the cache."""
        super().__delitem__(key)
        self._timestamps.pop(key, None)

    def get_timestamp(self, key: Any) -> float | None:
        """Get the timestamp of when an item was added to the cache. Returns None if the key is not in the cache."""
        return self._timestamps.get(key, None)

    def suspend_cached_value(self, key: Any) -> bool:
        """
        Suspend a value from the cache such that it can be restored later.

        Returns True if the value was successfully suspended.
        Raises KeyError if the key is not in the cache.
        """
        timestamp = self._timestamps.get(key, None)
        item = self.pop(key, None)
        if item is not None and timestamp is not None:
            self._suspended_values[key] = item
            self._suspended_timestamps[key] = timestamp
            return True
        raise KeyError(f"Key {key} not found in cache")

    def restore_suspended_value(self, key: Any) -> bool:
        """
        Restore a suspended value to the cache.
        If the key is already in the cache, the existing value will be overwritten.

        Returns True if the value was successfully restored.
        Raises KeyError if the key is not in the suspended values.
        """
        item = self._suspended_values.pop(key, None)
        timestamp = self._suspended_timestamps.pop(key, None)
        if item is not None and timestamp is not None:
            if key in self:
                logger.warning(f"Key {key} already in cache, overwriting with suspended value")
            self.__setitem__(key, item, timestamp=timestamp)
            return True
        raise KeyError(f"Key {key} not found in suspended values")

    def delete_suspended_value(self, key: Any) -> bool:
        """
        Delete a suspended value.

        Returns True if the value was successfully deleted.
        Raises KeyError if the key is not in the suspended values.
        """
        item = self._suspended_values.pop(key, None)
        timestamp = self._suspended_timestamps.pop(key, None)
        if item is not None and timestamp is not None:
            return True
        raise KeyError(f"Key {key} not found in suspended values")


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
