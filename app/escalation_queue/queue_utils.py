import logging
from typing import Any

from groundlight import Groundlight
from model import ImageQuery

from app.core.utils import get_formatted_timestamp_str, safe_call_sdk
from app.escalation_queue.queue_writer import EscalationInfo, QueueWriter, SubmitImageQueryParams

logger = logging.getLogger(__name__)


def write_escalation_to_queue(
    writer: QueueWriter,
    detector_id: str,
    image_bytes: bytes,
    # wait: float | None,
    patience_time: float | None,
    confidence_threshold: float,
    human_review: str | None,
    metadata: dict[str, Any] | None,
    image_query_id: str | None,
):
    submit_iq_params = SubmitImageQueryParams(
        wait=0,
        patience_time=patience_time,
        confidence_threshold=confidence_threshold,
        human_review=human_review,
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


def safe_escalate_with_queue_write(
    gl: Groundlight,
    queue_writer: QueueWriter,
    detector_id: str,
    image_bytes: bytes,
    want_async: bool,
    patience_time: float | None,
    confidence_threshold: float,
    human_review: str,
    metadata: dict | None = None,
) -> ImageQuery:
    """
    This attempts to escalate an image query via the SDK. If it fails, it will catch the exception and write the
    escalation to the queue, then raise the exception.
    """
    try:
        return safe_call_sdk(
            gl.submit_image_query,
            detector=detector_id,
            image=image_bytes,
            want_async=want_async,
            wait=0,
            patience_time=patience_time,
            confidence_threshold=confidence_threshold,
            human_review=human_review,
            metadata=metadata,
        )
    except Exception as ex:
        # We try writing to the queue in the case of all exceptions. We definitely want to do this in the case where
        # the escalation failed because there was no internet connection. For other exceptions, the escalation might or
        # might not be successful upon retry (e.g., if the request is malformed, it will error again). But the
        # escalation queue process will handle these errors and skip the escalation if it can't succceed, so we can
        # safely write it to the queue no matter what the exception here was.
        logger.info(f"Writing the escalation to the queue because there was an exception while escalating: {ex=}.")
        write_escalation_to_queue(
            writer=queue_writer,
            image_bytes=image_bytes,
            patience_time=patience_time,
            confidence_threshold=confidence_threshold,
            human_review=human_review,
            metadata=metadata,
            image_query_id=None,
        )
        raise ex
