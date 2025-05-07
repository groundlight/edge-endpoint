import json
import logging
import os
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status
from groundlight import Groundlight, GroundlightClientError, ImageQuery
from urllib3.exceptions import MaxRetryError

from app.core.utils import safe_call_sdk, wait_for_connection
from app.escalation_queue.constants import MAX_RETRY_ATTEMPTS
from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.queue_writer import EscalationInfo

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _groundlight_client() -> Groundlight:  # TODO this is duplicated from metricreporting.py
    """Returns a Groundlight client instance with EE-wide credentials for reporting metrics."""
    # Don't specify an API token here - it will use the environment variable.
    return Groundlight()


def consume_queued_escalation(escalation_str: str, gl: Groundlight | None = None) -> tuple[ImageQuery | None, bool]:
    """
    Consumes the escalation string and tries to do the escalation.
    Returns a tuple:
    - The first element is an ImageQuery if the escalation is successful and None otherwise.
    - The second element is a bool which is True if retrying the escalation might succeed, and False if the escalation
        should not be tried again.
            - For example, if the image could not be loaded, there is no point in retrying.
    """
    # TODO how to handle when there's no connection and GL client can't be created?

    escalation_info = EscalationInfo(**json.loads(escalation_str))
    logger.info(
        f"Consumed queued escalation for detector {escalation_info.detector_id} at {escalation_info.timestamp}."
    )

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
        res = safe_call_sdk(
            gl.submit_image_query,
            detector=escalation_info.detector_id,
            image=image_bytes,
            wait=submit_iq_params.wait,
            patience_time=submit_iq_params.patience_time,
            confidence_threshold=submit_iq_params.confidence_threshold,
            human_review=submit_iq_params.human_review,
            want_async=True,  # Escalations from the queue are always async
            image_query_id=submit_iq_params.image_query_id,
            metadata=submit_iq_params.metadata,
        )

        logger.info("Successfully completed escalation.")
        return res, False  # Should not retry because a result was achieved.
    except MaxRetryError as ex:  # When the GL object exists but there's no connection while trying to send request
        logger.info(f"Got MaxRetryError! {ex=}")
        logger.info("This likely means we currently have no internet connection. Will retry.")
        return None, True  # Should retry because the escalation may succeed once connection is restored.
    except HTTPException as ex:
        if (
            ex.status_code == status.HTTP_400_BAD_REQUEST
        ):  # TODO do we want to validate escalation args when it's attempted, so that we don't end up having to scrap it here?
            logger.info(f"Got HTTPException with status code 400. Scrapping the escalation. {ex=}")
            return None, False  # Should not retry because the request is malformed.
        else:
            logger.info(f"Got HTTPException with unhandled status code {ex.status_code}. {ex=}")
            return None, True  # Should retry because this may have been a one-off issue.
    except Exception as ex:
        logger.info(f"Got some other kind of exception that we aren't explicitly catching. {ex=}")
        return None, True  # Should retry because this may have been a one-off issue.


def read_from_escalation_queue(reader: QueueReader) -> None:
    queued_escalation = reader.get_next_line()
    if queued_escalation is not None:
        retry_count = 0
        should_retry_escalation = True
        escalation_result = None
        while should_retry_escalation:
            wait_for_connection(float("inf"))  # Wait for connection before trying to escalate

            escalation_result, should_try_again = consume_queued_escalation(queued_escalation)
            if escalation_result is None:
                logger.info("Escalation failed.")
                if should_try_again:
                    retry_count += 1
                    if (
                        retry_count < MAX_RETRY_ATTEMPTS
                    ):  # TODO as of now we will skip an escalation if we gain and then lose connection too many times. Is that okay?
                        logger.info(f"Retrying escalation (attempt {retry_count}/{MAX_RETRY_ATTEMPTS})...")
                    else:
                        logger.info(f"Escalation failed after {MAX_RETRY_ATTEMPTS} attempts. Moving to next item.")
                        should_retry_escalation = False
                else:
                    # If there isn't reason to try again, we move on to the next escalation.
                    logger.info("Moving to next item without retrying.")
                    should_retry_escalation = False
            else:
                logger.info(f"Escalation succeeded. {escalation_result=}")
                should_retry_escalation = False
        logger.info(f"Stopping escalation process. Got {escalation_result=}")


def manage_read_escalation_queue(reader: QueueReader) -> None:
    while True:
        read_from_escalation_queue(reader)


if __name__ == "__main__":
    logger.info("Starting escalation queue reader.")

    queue_reader = QueueReader()
    manage_read_escalation_queue(queue_reader)
