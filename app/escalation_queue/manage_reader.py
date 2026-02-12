import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status
from groundlight import Groundlight, GroundlightClientError, ImageQuery
from urllib3.exceptions import MaxRetryError, ReadTimeoutError

from app.core.utils import safe_call_sdk
from app.escalation_queue.failed_escalations import record_failed_escalation
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


def _escalate_once(escalation_info: EscalationInfo, submit_iq_request_timeout_s: int | tuple[int, int]) -> ImageQuery:
    """
    Consumes escalation info for a query and attempts to complete the escalation.

    Args:
        escalation_info (EscalationInfo): Information required to perform the escalation.
        submit_iq_request_timeout_s (int | tuple[int, int]): Request timeout for the image query submission request.
            This will be passed to submit_image_query as request_timeout.

    Returns:
        ImageQuery: The escalated ImageQuery result.
    """

    logger.debug(
        f"Escalating queued escalation with ID {escalation_info.submit_iq_params.image_query_id} for detector "
        f"{escalation_info.detector_id} with timestamp {escalation_info.timestamp}."
    )
    gl = _groundlight_client()
    image_path = Path(escalation_info.image_path_str)
    image_bytes = image_path.read_bytes()
    submit_iq_params = escalation_info.submit_iq_params
    return safe_call_sdk(
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


def is_retryable_exception(exc: BaseException) -> bool:
    """Returns True if an escalation should be retried for the given exception."""
    # Transient client/network failures. These typically resolve after connectivity is restored.
    if isinstance(exc, (GroundlightClientError, MaxRetryError, ReadTimeoutError)):
        return True
    # Cloud-side throttling. Waiting and retrying is expected to succeed.
    if isinstance(exc, HTTPException) and exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return True
    # Everything else is treated as a permanent failure (including HTTP 400 and missing image file).
    return False


def consume_queued_escalation(
    escalation_info: EscalationInfo,
) -> ImageQuery:
    """
    Attempts to escalate a queued escalation, retrying based on whether the escalation might succeed in the future.
    """
    submit_iq_request_timeout_s = (5, 15)  # How long the image query request should be allowed to try to complete.
    # The first element of the tuple is the connect timeout and the second is the read timeout.

    retry_count = 0

    while True:
        try:
            return _escalate_once(escalation_info, submit_iq_request_timeout_s)
        except Exception as exc:
            is_retryable = is_retryable_exception(exc)
            if not is_retryable:
                raise

        logger.info(f"Escalation attempt {retry_count + 1} failed.")
        # We'll use shorter connect timeout on retries since we expect we have bad network connectivity.
        submit_iq_request_timeout_s = (
            1,
            15,
        )
        wait_time = RETRY_WAIT_TIMES[min(retry_count, len(RETRY_WAIT_TIMES) - 1)]
        logger.info(f"Retrying escalation. Waiting {wait_time} seconds before next retry.")
        time.sleep(wait_time)
        retry_count += 1


def read_from_escalation_queue(reader: QueueReader, request_cache: RequestCache) -> None:
    """Reads escalations from the queue reader and attempts to escalates them."""
    # Because the QueueReader will block until it has something to yield, this will loop forever
    for escalation in reader:
        logger.debug("Got queued escalation from reader.")
        escalation_info: EscalationInfo | None = None
        try:
            escalation_info = EscalationInfo(**json.loads(escalation.strip()))
            if not request_cache.contains(escalation_info.request_id):
                result = consume_queued_escalation(escalation_info)

                # Cache the request ID so that we don't repeat duplicate requests
                request_cache.add(escalation_info.request_id)
                logger.info(f"Escalation succeeded for escalation with ID {result.id}.")
            else:
                logger.debug("Duplicate request ID received: %s. Skipping", escalation_info.request_id)
        except Exception as e:
            logger.error("Escalation failed, moving on.", exc_info=True)
            record_failed_escalation(escalation, e)
        finally:
            # Delete the image
            if escalation_info is not None:
                Path(escalation_info.image_path_str).unlink(missing_ok=True)


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
