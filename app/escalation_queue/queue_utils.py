from groundlight import Groundlight
from model import ImageQuery

from app.core.utils import get_formatted_timestamp_str, safe_call_sdk
from app.escalation_queue.models import EscalationInfo, SubmitImageQueryParams
from app.escalation_queue.queue_writer import QueueWriter
from app.utils.loghelper import create_logger

logger = create_logger(__name__, component="escalation-queue-reader")


def write_escalation_to_queue(
    writer: QueueWriter, detector_id: str, image_bytes: bytes, submit_iq_params: SubmitImageQueryParams, request_id: str
) -> None:
    """Writes an escalation to the queue. On failure, logs an error and does NOT raise an exception."""
    try:  # We don't want this to ever raise an exception because it's called synchronously before we return an answer.
        timestamp = get_formatted_timestamp_str()
        image_path_str = writer.write_image_bytes(image_bytes, detector_id, timestamp)

        escalation_info = EscalationInfo(
            timestamp=timestamp,
            detector_id=detector_id,
            image_path_str=image_path_str,
            submit_iq_params=submit_iq_params,
            request_id=request_id,
        )
        writer.write_escalation(escalation_info)
    except Exception as e:
        logger.error(f"Failed to write escalation to queue for detector {detector_id} with error {e}.")


def safe_escalate_with_queue_write(
    gl: Groundlight,
    queue_writer: QueueWriter,
    detector_id: str,
    image_bytes: bytes,
    want_async: bool,
    submit_iq_params: SubmitImageQueryParams,
    request_id: str,
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
            patience_time=submit_iq_params.patience_time,
            confidence_threshold=submit_iq_params.confidence_threshold,
            human_review=submit_iq_params.human_review,
            metadata=submit_iq_params.metadata,
        )
    except Exception as ex:
        # We try writing to the queue in the case of all exceptions. We definitely want to do this in the case where
        # the escalation failed because there was no internet connection. For other exceptions, the escalation might or
        # might not be successful upon retry (e.g., if the request is malformed, it will error again). But the
        # escalation queue process will handle these errors and skip the escalation if it can't succceed, so we can
        # safely write it to the queue no matter what the exception here was.
        logger.info(
            f"Writing an escalation for detector {detector_id} to the queue because there was an exception while "
            f"escalating: {ex=}."
        )
        write_escalation_to_queue(
            writer=queue_writer,
            detector_id=detector_id,
            image_bytes=image_bytes,
            submit_iq_params=submit_iq_params,
            request_id=request_id,
        )
        raise ex
