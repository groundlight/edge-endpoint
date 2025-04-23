import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status
from groundlight import Groundlight, ImageQuery
from urllib3.exceptions import MaxRetryError

from app.core.utils import safe_call_sdk
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


def consume_queued_escalation(
    escalation_str: str, gl: Groundlight = _groundlight_client()
) -> tuple[ImageQuery | None, bool]:
    """
    Consumes the escalation string and tries to do the escalation.
    Returns a tuple:
    - The first element is an ImageQuery if the escalation is successful and None otherwise.
    - The second element is a bool which is True if the parent function should retry and False otherwise.
    """
    # TODO how to handle when there's no connection and GL client can't be created?

    escalation_info = EscalationInfo(**json.loads(escalation_str))
    logger.info(
        f"Consumed queued escalation. Escalation IQ for detector {escalation_info.detector_id} at {escalation_info.timestamp}."
    )

    image_path = Path(escalation_info.image_path_str)
    image_bytes = image_path.read_bytes()

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
            want_async=submit_iq_params.want_async,
            image_query_id=submit_iq_params.image_query_id,
            metadata=submit_iq_params.metadata,
        )

        # If we got here, we successfully completed the escalation
        logger.info("Successfully completed escalation.")

        return res, False
    except MaxRetryError as ex:  # When the GL object exists but there's no connection while trying to send request
        logger.info(f"Got MaxRetryError! {ex=}")
        logger.info("This likely means we currently have no internet connection. Will retry.")
        return None, True
    # except GroundlightClientError as ex:  # When trying to create GL object w/o connection
    #     logger.info(f"Got GroundlightClientError! {ex=}")
    except HTTPException as ex:  # Invalid request, not found, etc.
        logger.info(f"Got HTTPException! {ex=}")
        if ex.status_code == status.HTTP_400_BAD_REQUEST:
            logger.info("Got HTTPException with status code 400. Scrapping the escalation.")
            return None, False
        else:
            # TODO catch other errors?
            logger.info(f"Got HTTPException with unhandled status code {ex.status_code}. Scrapping the escalation.")
            return None, False
    except Exception as ex:
        logger.info(f"Got some other kind of exception that we aren't explicitly catching! {ex=}")


def manage_read_escalation_queue(reader: QueueReader):
    while True:
        queued_escalation = reader.get_next_line()
        if queued_escalation is not None:
            escalation_result, should_retry = consume_queued_escalation(queued_escalation)
            if escalation_result is None:
                logger.info(
                    f"Received None from `consume_queued_escalation`, meaning the escalation failed. {should_retry=}"
                )
                # TODO implement retrying behavior
            else:
                logger.info(f"{escalation_result=}")
        time.sleep(1)


if __name__ == "__main__":
    logger.info("Starting escalation queue reader.")

    queue_reader = QueueReader()
    manage_read_escalation_queue(queue_reader)
