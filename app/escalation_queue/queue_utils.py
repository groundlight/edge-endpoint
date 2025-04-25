import logging
import socket
import time
from typing import Any

from cachetools import TTLCache, cached

from app.core.utils import get_formatted_timestamp_str
from app.escalation_queue.constants import (
    CONNECTION_STATUS_TTL_SECS,
    CONNECTION_TEST_HOST,
    CONNECTION_TEST_PORT,
    CONNECTION_TIMEOUT,
)
from app.escalation_queue.queue_writer import EscalationInfo, QueueWriter, SubmitImageQueryParams

logger = logging.getLogger(__name__)


def write_escalation_to_queue(
    writer: QueueWriter,
    detector_id: str,
    image_bytes: bytes,
    wait: float | None,
    patience_time: float | None,
    confidence_threshold: float,
    human_review: str | None,
    want_async: bool,
    metadata: dict[str, Any] | None,
    image_query_id: str | None,
):
    submit_iq_params = SubmitImageQueryParams(
        wait=wait,
        patience_time=patience_time,
        confidence_threshold=confidence_threshold,
        human_review=human_review,
        want_async=want_async,
        metadata=metadata,
        image_query_id=image_query_id,
    )

    timestamp = get_formatted_timestamp_str()
    image_path = writer.write_image_bytes(image_bytes, detector_id, timestamp)

    escalation_info = EscalationInfo(
        timestamp=timestamp,
        detector_id=detector_id,
        image_path=image_path,
        submit_iq_params=submit_iq_params,
    )
    writer.write_escalation(escalation_info)  # TODO retry here?


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


def wait_for_connection() -> None:
    while not is_connected():
        time.sleep(1)  # TODO make configurable? or constant setting?
