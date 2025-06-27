import json
import logging
import os
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status
from groundlight import Groundlight, GroundlightClientError, ImageQuery
from urllib3.exceptions import MaxRetryError

from app.core.utils import safe_call_sdk
from app.escalation_queue.models import EscalationInfo
from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.queue_utils import is_already_escalated

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _groundlight_client() -> Groundlight:  # TODO this is duplicated from metricreporting.py
    """Returns a Groundlight client instance with EE-wide credentials for reporting metrics."""
    # Don't specify an API token here - it will use the environment variable.
    return Groundlight()  # TODO this will likely wait the default 10 seconds when there's no connection


def _escalate_once(  # noqa: PLR0911
    escalation_info: EscalationInfo, submit_iq_request_time_s: int, gl: Groundlight | None = None
) -> tuple[ImageQuery | None, bool]:
    """
    Consumes escalation info for a query and attempts to complete the escalation. TODO update
    Returns a tuple:
    - The first element is an ImageQuery if the escalation is successful and None otherwise.
    - The second element is a bool which is True if retrying the escalation might succeed, and False if the escalation
        should not be tried again.
            - For example, if the image could not be loaded, there is no point in retrying.
    """
    # TODO how to handle when there's no connection and GL client can't be created?

    logger.info(
        f"Consumed queued escalation for detector {escalation_info.detector_id} at {escalation_info.timestamp}."
    )

    # TODO is allowing a value to be passed just for testing? do we need to do this, or should we just always create it here?
    if gl is None:
        try:
            gl = _groundlight_client()
        except GroundlightClientError:
            logger.info("Got GroundlightClientError while trying to create the client. Will retry.")
            return None, True  # Should retry because the escalation may succeed once connection is restored.

    image_path = Path(escalation_info.image_path_str)
    try:
        image_bytes = image_path.read_bytes()
    except FileNotFoundError:
        logger.info(f"Could not locate image at path {image_path}. Skipping this escalation.")
        return None, False  # Should not retry because the image cannot be located.

    submit_iq_params = escalation_info.submit_iq_params
    try:
        if is_already_escalated(gl, submit_iq_params.image_query_id):
            logger.info(
                f"An image query with ID {submit_iq_params.image_query_id} already exists in the cloud, so we must "
                "have already escalated it. Skipping this escalation to avoid creating a duplicate."
            )
            return None, False  # Scrap escalation if it was previously completed.

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
            request_time=submit_iq_request_time_s,
        )

        logger.info("Successfully completed escalation.")
        return res, False  # Should not retry because the escalation was successful.
    except MaxRetryError as ex:  # When there's no connection while trying to send request
        logger.info(
            f"Got MaxRetryError! {ex=}. This likely means we currently have no internet connection. Will retry."
        )
        return None, True  # Should retry because the escalation may succeed once connection is restored.
    except HTTPException as ex:
        if ex.status_code == status.HTTP_400_BAD_REQUEST:
            logger.info(f"Got HTTPException with status code 400. Scrapping the escalation. {ex=}")
            return None, False  # Should not retry because the request is malformed.
        else:
            logger.info(f"Got HTTPException with unhandled status code {ex.status_code}. {ex=}")
            return None, False  # Do not retry.
    except Exception as ex:
        logger.info(f"Got some other kind of exception that we aren't explicitly catching. {ex=}")
        return None, False  # Do not retry.


def consume_queued_escalation(escalation_str: str) -> ImageQuery | None:
    escalation_info = EscalationInfo(**json.loads(escalation_str))

    should_retry_escalation = True
    escalation_result = None

    submit_iq_request_time_s = 5  # How long the request should be allowed to try to complete.

    while should_retry_escalation:
        escalation_result, should_try_again = _escalate_once(escalation_info, submit_iq_request_time_s)
        if escalation_result is None:
            logger.info("Escalation failed.")
            if should_try_again:
                logger.info("Retrying escalation.")
                should_retry_escalation = True
                submit_iq_request_time_s = 0.5  # Wait less time on retries, since we expect we don't have connection.
            else:
                # If there isn't reason to try again, we move on to the next escalation.
                logger.info("Moving to next item without retrying.")
                should_retry_escalation = False
        else:
            logger.info("Escalation succeeded.")
            should_retry_escalation = False

    return escalation_result


def read_from_escalation_queue(reader: QueueReader) -> None:
    for escalation in reader:
        result = consume_queued_escalation(escalation)
        if result is None:
            logger.info("Escalation permanently failed, moving on.")
        else:
            logger.info(f"Escalation succeeded with result {result}.")


if __name__ == "__main__":
    logger.info("Starting escalation queue reader.")

    queue_reader = QueueReader()
    read_from_escalation_queue(queue_reader)
