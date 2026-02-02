import json
import logging
import os
import random  # TODO: remove with temporary chaos injection block before shipping
import time
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status
from groundlight import Groundlight, GroundlightClientError, ImageQuery
from urllib3.exceptions import MaxRetryError, ReadTimeoutError

from app.core.utils import safe_call_sdk
from app.escalation_queue.dropped_escalations import DroppedEscalationReason, record_dropped_escalation
from app.escalation_queue.models import EscalationInfo
from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.request_cache import RequestCache

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Increasing lengths of time to wait before retrying an escalation, to avoid hammering the cloud
# service if it's down for some reason or if the user's throttling limit is reached.
RETRY_WAIT_TIMES = [0, 1, 5, 10, 30]


@lru_cache(maxsize=1)
def _groundlight_client() -> Groundlight:
    """Returns a Groundlight client instance with EE-wide credentials for escalating from the queue."""
    # Don't specify an API token here - it will use the environment variable.
    return Groundlight()  # NOTE this will wait the default 10 seconds when there's no connection.


def _escalate_once(  # noqa: PLR0911
    escalation_info: EscalationInfo, submit_iq_request_timeout_s: int | tuple[int, int]
) -> tuple[ImageQuery | None, bool, DroppedEscalationReason | None, str | None]:
    """
    Consumes escalation info for a query and attempts to complete the escalation.

    Args:
        escalation_info (EscalationInfo): Information required to perform the escalation.
        submit_iq_request_timeout_s (int): Timeout in seconds for the image query submission request. This will be
            passed to submit_image_query as the request_timeout.

    Returns:
        tuple[ImageQuery | None, bool]:
            - The first element is an ImageQuery if the escalation is successful and None otherwise.
            - The second element is a bool: True if retrying the escalation might succeed, False if the escalation
              should not be tried again.
              For example, if the image could not be loaded, there is no point in retrying.
    """
    logger.info(
        f"Consumed queued escalation with ID {escalation_info.submit_iq_params.image_query_id} for detector "
        f"{escalation_info.detector_id} with timestamp {escalation_info.timestamp}."
    )

    try:
        gl = _groundlight_client()
    except GroundlightClientError as ex:
        # We don't catch API token related exceptions here, since we want those to visibly fail. A
        # GroundlightClientError exception will be raised for other kinds of errors, including when the client could
        # not be created due to no internet connection.
        logger.info(f"Got error {ex=} while trying to create the Groundlight client. Will retry.")
        return (
            None,
            True,  # Should retry because the escalation may succeed if connection is down and gets restored.
            None,
            str(ex),
        )

    image_path = Path(escalation_info.image_path_str)
    try:
        image_bytes = image_path.read_bytes()
    except FileNotFoundError:
        logger.info(f"Could not locate image at path {image_path}. Skipping this escalation.")
        return None, False, DroppedEscalationReason.IMAGE_NOT_FOUND, f"image_path={image_path}"

    submit_iq_params = escalation_info.submit_iq_params
    try:
        res = safe_call_sdk(
            gl.submit_image_query,
            detector=escalation_info.detector_id,
            image=image_bytes,
            wait=0,  # Never want to wait when escalating from the queue
            patience_time=submit_iq_params.patience_time,
            confidence_threshold=submit_iq_params.confidence_threshold,
            human_review=submit_iq_params.human_review,
            want_async=True,  # Escalations from the queue are always async
            image_query_id=submit_iq_params.image_query_id,
            metadata=submit_iq_params.metadata,
            request_timeout=submit_iq_request_timeout_s,
        )
        return res, False, None, None  # Should not retry because the escalation was successful.
    except MaxRetryError as ex:
        # Raised when the API client tried to retry the request but did not succeed. This exception is most often seen
        # when there's network connectivity problems.
        logger.info(f"Got MaxRetryError, {ex=}. This could be due to network connectivity issues. Will retry.")
        return None, True, None, str(ex)  # Should retry because the escalation could succeed in the future.
    except ReadTimeoutError as ex:
        # Raised when the upstream server doesn't respond within the read timeout after connection. This exception is
        # most often seen when there's network connectivity problems.
        logger.info(f"Got ReadTimeoutError, {ex=}. This could be due to network connectivity issues. Will retry.")
        return None, True, None, str(ex)  # Should retry because the escalation could succeed in the future.
    except HTTPException as ex:
        if ex.status_code == status.HTTP_400_BAD_REQUEST:
            logger.info(
                "Got HTTPException with status code 400. This could be because we already escalated this query, in "
                "which case we can move on. This could also be due to a malformed request, which is not expected to "
                f"succeed upon retry. Scrapping the escalation. \nThe exception was: {ex}"
            )
            return None, False, DroppedEscalationReason.HTTP_400_BAD_REQUEST, str(ex)
        elif ex.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            logger.info(
                "Got HTTPException with status code 429. This likely means we have hit our throttling limit. Will "
                "retry."
            )
            # NOTE This could inspect the 'retry-after' key in the header response to find the exact time needed to
            # wait. For now we just do our normal retry backoff.
            return (
                None,
                True,
                None,
                str(ex),
            )  # Should retry because the escalation may succeed after some time has passed.
        else:
            logger.info(f"Got HTTPException with unhandled status code {ex.status_code}. {ex=}")
            return None, False, DroppedEscalationReason.HTTP_ERROR, str(ex)
    except Exception as ex:
        logger.info(f"Got some other kind of exception that we aren't explicitly catching. {ex=}")
        return None, False, DroppedEscalationReason.UNHANDLED_EXCEPTION, str(ex)  # Do not retry.


def consume_queued_escalation(
    escalation_str: str, request_cache: RequestCache, delete_image: bool | None = True
) -> ImageQuery | None:
    """
    Attempts to escalate a queued escalation, retrying based on whether the escalation might succeed in the future.

    The `delete_image` argument is used by tests only, and otherwise defaults to True.
    """
    # Skip empty/whitespace lines
    stripped = escalation_str.strip()
    if not stripped:
        logger.warning("Skipping empty line in escalation queue.")
        record_dropped_escalation(reason=DroppedEscalationReason.EMPTY_LINE, raw_line=escalation_str)
        return None

    # Skip lines with null bytes (corruption indicator)
    if "\x00" in escalation_str:
        logger.warning("Skipping corrupted line with null bytes in escalation queue.")
        record_dropped_escalation(reason=DroppedEscalationReason.CORRUPTED_NULL_BYTES, raw_line=escalation_str)
        return None

    try:
        escalation_info = EscalationInfo(**json.loads(stripped))
    except json.JSONDecodeError as e:
        logger.warning(f"Skipping line with invalid JSON: {e}")
        record_dropped_escalation(reason=DroppedEscalationReason.INVALID_JSON, raw_line=escalation_str, error=str(e))
        return None
    except Exception as e:
        logger.warning(f"Skipping line that failed to parse as EscalationInfo: {e}")
        record_dropped_escalation(
            reason=DroppedEscalationReason.MALFORMED_ESCALATION_INFO, raw_line=escalation_str, error=str(e)
        )
        return None

    if request_cache.contains(escalation_info.request_id):
        logger.info(
            "Skipping escalation because we've already done an escalation related to request ID "
            f"{escalation_info.request_id}."
        )
        return None

    should_retry_escalation = True
    escalation_result = None
    last_failure_reason: DroppedEscalationReason | None = None
    last_failure_error: str | None = None

    submit_iq_request_timeout_s = (5, 15)  # How long the image query request should be allowed to try to complete.
    # The first element of the tuple is the connect timeout and the second is the read timeout.

    retry_count = 0

    while should_retry_escalation:
        escalation_result, should_try_again, failure_reason, failure_error = _escalate_once(
            escalation_info, submit_iq_request_timeout_s
        )
        if escalation_result is None:
            last_failure_reason = failure_reason
            last_failure_error = failure_error
            logger.info(f"Escalation attempt {retry_count + 1} failed.")
            if should_try_again:
                should_retry_escalation = True
                submit_iq_request_timeout_s = (
                    1,
                    15,
                )  # Shorter connect timeout on retries since we expect we have bad network connectivity.
                wait_time = RETRY_WAIT_TIMES[min(retry_count, len(RETRY_WAIT_TIMES) - 1)]
                logger.info(f"Retrying escalation. Waiting {wait_time} seconds before next retry.")
                time.sleep(wait_time)
                retry_count += 1
            else:
                # If there isn't reason to try again, we move on to the next escalation.
                should_retry_escalation = False
        else:  # Successfully escalated.
            should_retry_escalation = False

    if escalation_result is None:
        record_dropped_escalation(
            reason=last_failure_reason or DroppedEscalationReason.UNHANDLED_EXCEPTION,
            escalation_info=escalation_info,
            error=last_failure_error,
            retry_count=retry_count,
        )

    # Once we're done with this escalation, add the request ID to the cache so that we don't try to escalate duplicate
    # requests (stemming from, e.g., client-side retries).
    request_cache.add(escalation_info.request_id)

    if delete_image:
        # Delete image when moving on from the escalation (whether it was successfully completed or not).
        image_path = Path(escalation_info.image_path_str)
        image_path.unlink(missing_ok=True)

    return escalation_result


def inject_chaos(escalation: str) -> str:
    """
    TODO: Remove this chaos injection function before shipping.
    """
    chaos_prob = 1 / 5
    if random.random() >= chaos_prob:
        return escalation

    chaos_mode = random.choice(["null_bytes", "invalid_json", "empty_line", "delete_image"])
    logger.warning(f"Chaos injection enabled. Injecting mode={chaos_mode}.")

    if chaos_mode == "null_bytes":
        return "\x00\x00corrupted\x00\x00"
    if chaos_mode == "invalid_json":
        return "this is not json {"
    if chaos_mode == "empty_line":
        return "   \n\t  "
    if chaos_mode == "delete_image":
        try:
            data = json.loads(escalation.strip())
            image_path_str = data.get("image_path_str")
            if image_path_str:
                Path(image_path_str).unlink(missing_ok=True)
        except Exception:
            logger.exception("Chaos injector failed to delete image.")

    return escalation


def read_from_escalation_queue(reader: QueueReader, request_cache: RequestCache) -> None:
    """Reads escalations from the queue reader and attempts to escalates them."""
    # Because the QueueReader will block until it has something to yield, this will loop forever
    for escalation in reader:
        # TODO: Remove this chaos injection function before shipping.
        escalation = inject_chaos(escalation)

        logger.info("Got queued escalation from reader.")
        result = consume_queued_escalation(escalation, request_cache)
        if result is None:
            logger.error("Escalation permanently failed or skipped, moving on.")
        else:
            logger.info(f"Escalation succeeded for escalation with ID {result.id}.")


if __name__ == "__main__":
    logger.info("Starting escalation queue reader.")

    queue_reader = QueueReader()
    # We cache recently escalated request IDs so that we can avoid escalating entries in the queue that come from the
    # same initial request. If a client sends a request to the edge and receives an exception such as an HTTP 504 error,
    # the Groundlight SDK will automatically retry the request, sending the same query parameters to the edge afresh
    # each time. This could result in escalating the same request to the cloud multiple times, since each instance of
    # the query would be written to the queue with a different image query ID. Because the request ID is constant
    # between retries, we can use that to detect and skip duplicate entries in the queue. If we implement a different
    # way of preventing retries on the edge in the future, this can be removed.
    request_cache = RequestCache()

    read_from_escalation_queue(queue_reader, request_cache)
