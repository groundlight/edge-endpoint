import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import Mock, call, patch

import ksuid
import pytest
from fastapi import HTTPException, status
from groundlight import GroundlightClientError
from urllib3.exceptions import MaxRetryError

from app.core.utils import get_formatted_timestamp_str
from app.escalation_queue.constants import MAX_QUEUE_FILE_LINES, MAX_RETRY_ATTEMPTS
from app.escalation_queue.manage_reader import consume_queued_escalation, read_from_escalation_queue
from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.queue_writer import EscalationInfo, QueueWriter, SubmitImageQueryParams

### Helper functions


def generate_test_escalation(
    timestamp_str: str = get_formatted_timestamp_str(),
    submit_iq_params: SubmitImageQueryParams = SubmitImageQueryParams(
        wait=None,
        patience_time=None,
        confidence_threshold=0.9,
        human_review=None,
        want_async=False,
        metadata={"test_key": "test_value"},
        image_query_id=None,
    ),
    detector_id: str = "test_id",
    image_path: str = "test/assets/cat.jpeg",
) -> EscalationInfo:
    data = {
        "timestamp": timestamp_str,
        "detector_id": detector_id,
        "image_path_str": image_path,
        "submit_iq_params": submit_iq_params,
    }
    return EscalationInfo(**data)


def get_num_tracked_escalations(reader: QueueReader) -> int:
    """Get the number of escalations recorded in the reader's tracking file. Will return 0 if there is no such file."""
    if reader.current_tracking_file_path is None:
        return 0
    with reader.current_tracking_file_path.open(mode="r") as f:
        line = f.readline()
        return len(line)


def assert_file_length(file_path: str, expected_lines: int):
    """Assert that the file at the specified file path has the expected number of lines."""
    with open(file_path, "r") as f:
        num_lines = len(f.readlines())
        assert num_lines == expected_lines


def assert_contents_of_next_read_line(reader: QueueReader, expected_result: EscalationInfo | None):  # TODO rename
    """Assert that the next read line matches the expected result."""
    next_escalation_str = reader.get_next_line()
    next_escalation = None if next_escalation_str is None else EscalationInfo(**json.loads(next_escalation_str))
    assert next_escalation == expected_result


def escalation_info_to_str(escalation_info: EscalationInfo) -> str:
    return f"{json.dumps(escalation_info.model_dump())}\n"


### Fixtures


@pytest.fixture
def timestamp_str() -> str:
    return get_formatted_timestamp_str()


@pytest.fixture
def test_image_bytes() -> bytes:
    image_path = Path("test/assets/cat.jpeg")
    return image_path.read_bytes()


@pytest.fixture
def test_escalation() -> EscalationInfo:
    return generate_test_escalation()


@pytest.fixture
def base_dir() -> Generator[str, None, None]:
    temp_dir = os.path.join(tempfile.gettempdir(), f"test-escalation-queue-{ksuid.KsuidMs()}")
    os.makedirs(temp_dir, exist_ok=True)
    yield temp_dir
    # Clean up the directory once the test finishes
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def writer(base_dir: str) -> QueueWriter:
    return QueueWriter(base_dir=base_dir)


@pytest.fixture
def second_writer(base_dir: str) -> QueueWriter:  # TODO can do this in cleaner way?
    return QueueWriter(base_dir=base_dir)


@pytest.fixture
def reader(base_dir: str) -> QueueReader:
    return QueueReader(base_dir)


### Writer tests


def test_successive_writes_go_to_same_file(writer: QueueWriter, test_escalation: EscalationInfo):
    """Verify that successive escalation writes go to the same file."""
    for i in range(1, 4):
        assert writer.write_escalation(test_escalation)
        assert_file_length(writer.last_file_path, i)
        assert writer.num_lines_written_to_file == i


def test_write_to_different_file(writer: QueueWriter, test_escalation: EscalationInfo):
    """Verify that the writer uses a new file when the previous one is gone."""
    assert writer.write_escalation(test_escalation)
    first_file_path = writer.last_file_path
    assert_file_length(first_file_path, 1)
    assert writer.num_lines_written_to_file == 1

    first_file_path.unlink()
    assert writer.write_escalation(test_escalation)
    assert_file_length(writer.last_file_path, 1)
    assert first_file_path != writer.last_file_path
    assert writer.num_lines_written_to_file == 1


def test_separate_writers_write_to_different_files(
    writer: QueueWriter, second_writer: QueueWriter, test_escalation: EscalationInfo
):
    """Verify that separate writers will write to separate files."""
    assert writer.write_escalation(test_escalation)
    assert second_writer.write_escalation(test_escalation)

    assert not writer.last_file_path.samefile(second_writer.last_file_path)

    assert_file_length(writer.last_file_path, 1)
    assert_file_length(second_writer.last_file_path, 1)


def test_writer_respects_file_length_limit(writer: QueueWriter, test_escalation: EscalationInfo):
    """Verify that the writer starts writing to a new file when a file reaches the max allowed line length."""
    for i in range(MAX_QUEUE_FILE_LINES):
        assert writer.write_escalation(test_escalation)
        assert_file_length(writer.last_file_path, i + 1)
        assert writer.num_lines_written_to_file == i + 1

    first_file_path = writer.last_file_path
    assert writer.write_escalation(test_escalation)
    assert_file_length(writer.last_file_path, 1)
    assert writer.num_lines_written_to_file == 1
    assert not first_file_path.samefile(writer.last_file_path)


def test_writer_can_write_image(writer: QueueWriter, timestamp_str: str, test_image_bytes: bytes):
    """Verify that basic image writing works properly."""
    detector_id = "test_id"
    image_path = writer.write_image_bytes(test_image_bytes, detector_id, timestamp_str)
    assert detector_id in image_path
    assert timestamp_str in image_path

    image_path = Path(image_path)
    assert image_path.is_file()

    saved_bytes = image_path.read_bytes()
    assert saved_bytes == test_image_bytes


def test_writer_saves_images_to_unique_paths(writer: QueueWriter, timestamp_str: str, test_image_bytes: bytes):
    """Verify that multiple images saved with the same detector ID and timestamp are saved to unique paths."""
    detector_id = "test_id"
    first_image_path = writer.write_image_bytes(test_image_bytes, detector_id, timestamp_str)
    first_image_path = Path(first_image_path)
    assert first_image_path.is_file()

    second_image_path = writer.write_image_bytes(test_image_bytes, detector_id, timestamp_str)
    second_image_path = Path(second_image_path)
    assert second_image_path.is_file()

    assert not first_image_path.samefile(second_image_path)


### Reader tests


def test_read_with_empty_queue(reader: QueueReader):
    """Verify that the reader always returns None when there is nothing in the queue."""
    for _ in range(5):
        assert_contents_of_next_read_line(reader, None)


def test_reader_moves_file(reader: QueueReader, writer: QueueWriter, test_escalation: EscalationInfo):
    """Verify that the reader moves the file being read."""
    assert writer.write_escalation(test_escalation)
    written_to_path = writer.last_file_path

    assert_contents_of_next_read_line(reader, test_escalation)

    assert reader.current_file_path != written_to_path
    assert not written_to_path.exists()


def test_reader_finds_new_file(writer: QueueWriter, reader: QueueReader, test_escalation: EscalationInfo):
    """Verify that the reader can find and read from a file created after the reader was instantiated."""
    assert writer.write_escalation(test_escalation)
    first_written_path = writer.last_file_path

    assert_contents_of_next_read_line(reader, test_escalation)

    assert writer.write_escalation(test_escalation)
    second_written_path = writer.last_file_path
    assert first_written_path != second_written_path  # Wrote to a different file

    assert_contents_of_next_read_line(reader, test_escalation)


def test_read_multiple_lines_from_same_file(reader: QueueReader, writer: QueueWriter):
    """
    Verify that the reader can read multiple lines from the same file in the correct order, and returns None when there
    are none left.
    """
    num_lines = 3
    test_escalations = [generate_test_escalation(detector_id=f"test_id_{i}") for i in range(num_lines)]

    for escalation in test_escalations:
        assert writer.write_escalation(escalation)

    for escalation in test_escalations:
        assert_contents_of_next_read_line(reader, escalation)
    assert_contents_of_next_read_line(reader, None)


def test_reader_selects_oldest_file(reader: QueueReader, writer: QueueWriter, second_writer: QueueWriter):
    """Verify that the reader reads from the oldest file first."""
    test_escalation_1 = generate_test_escalation(detector_id="test_id_1")
    test_escalation_2 = generate_test_escalation(detector_id="test_id_2")

    assert writer.write_escalation(test_escalation_1)
    assert second_writer.write_escalation(test_escalation_2)
    assert not writer.last_file_path.samefile(second_writer.last_file_path)

    assert_contents_of_next_read_line(reader, test_escalation_1)
    assert_contents_of_next_read_line(reader, test_escalation_2)


def test_reader_deletes_empty_file(reader: QueueReader, writer: QueueWriter, test_escalation: EscalationInfo):
    """Verify that the reader deletes a file when it reads all the lines from it."""
    num_lines = 3
    for _ in range(num_lines):
        assert writer.write_escalation(test_escalation)

    for _ in range(num_lines):
        assert_contents_of_next_read_line(reader, test_escalation)

    previous_reading_path = reader.current_file_path
    assert previous_reading_path is not None

    assert_contents_of_next_read_line(reader, None)
    assert reader.current_file_path is None
    assert not previous_reading_path.exists()


def test_reader_basic_tracking(reader: QueueReader, writer: QueueWriter, test_escalation: EscalationInfo):
    """Verify that the reader tracks escalations in a separate file properly."""
    num_lines = 3
    for _ in range(num_lines):
        assert writer.write_escalation(test_escalation)

    for i in range(num_lines):
        assert_contents_of_next_read_line(reader, test_escalation)
        assert get_num_tracked_escalations(reader) == i + 1

    assert_contents_of_next_read_line(reader, None)
    assert reader.current_tracking_file_path is None


### Escalation consumption tests


def test_consume_escalation_successful(test_escalation: EscalationInfo):
    """Verifies that basic escalation consumption is successful."""
    test_escalation_str = escalation_info_to_str(test_escalation)
    with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()):
        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
        assert escalation_result is not None
        assert not should_try_again


def test_consume_escalation_image_not_found(test_escalation: EscalationInfo):
    """Verifies that no error is raised and the escalation is skipped when the image cannot be found."""
    test_escalation.image_path_str = "not-a-real-path"
    test_escalation_str = escalation_info_to_str(test_escalation)

    escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
    assert escalation_result is None
    assert not should_try_again


def test_consume_escalation_no_connection(test_escalation: EscalationInfo):
    """Verifies that no error is raised and a retry is prompted when there is no connection."""
    test_escalation_str = escalation_info_to_str(test_escalation)
    with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()) as mock_sdk_call:
        mock_sdk_call.side_effect = MaxRetryError(pool=None, url=None)
        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
        assert escalation_result is None
        assert should_try_again


def test_consume_escalation_bad_request(test_escalation: EscalationInfo):
    """Verifies that no error is raised and no retry is prompted when a bad request exception is encountered."""
    test_escalation.submit_iq_params.human_review = "NOT A VALID OPTION"
    test_escalation_str = escalation_info_to_str(test_escalation)
    with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()) as mock_sdk_call:
        mock_sdk_call.side_effect = HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
        assert escalation_result is None
        assert not should_try_again


def test_consume_escalation_other_http_exception(test_escalation: EscalationInfo):
    """Verifies that no error is raised and a retry is prompted when any non-handled HTTP exception is encountered."""
    test_escalation_str = escalation_info_to_str(test_escalation)
    with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()) as mock_sdk_call:
        mock_sdk_call.side_effect = HTTPException(status_code=status.HTTP_418_IM_A_TEAPOT)
        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
        assert escalation_result is None
        assert should_try_again


def test_consume_escalation_gl_client_creation_failure(test_escalation: EscalationInfo):
    """Verifies that no error is raised and a retry is prompted when it fails to create a Groundlight client."""
    test_escalation_str = escalation_info_to_str(test_escalation)

    with patch("app.escalation_queue.manage_reader._groundlight_client", return_value=Mock()) as mock_gl_client:
        mock_gl_client.side_effect = GroundlightClientError()
        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str)
        assert escalation_result is None
        assert should_try_again


### Escalation queue management tests


def test_queue_management_basic_functionality(writer: QueueWriter, reader: QueueReader):
    """Verifies that basic queue management works when reading from the queue and consuming the queued escalations."""
    num_escalations = 3
    test_escalations = [generate_test_escalation(detector_id=f"test_id_{i}") for i in range(num_escalations)]
    for escalation in test_escalations:
        assert writer.write_escalation(escalation)

    with patch(
        "app.escalation_queue.manage_reader.consume_queued_escalation",
        return_value=(Mock(), False),  # TODO put patches into helper(s)?
    ) as mock_consume_escalation:
        with patch("app.escalation_queue.manage_reader.wait_for_connection") as mock_wait_for_connection:
            # Ensure the escalations we wrote get consumed
            for escalation in test_escalations:
                read_from_escalation_queue(reader)
                mock_wait_for_connection.assert_called_once()
                mock_consume_escalation.assert_called_once_with(escalation_info_to_str(escalation))
                mock_wait_for_connection.reset_mock()
                mock_consume_escalation.reset_mock()

            # Nothing more in the queue to read
            read_from_escalation_queue(reader)
            mock_wait_for_connection.assert_not_called()
            mock_consume_escalation.assert_not_called()
            mock_wait_for_connection.reset_mock()
            mock_consume_escalation.reset_mock()

            # Write another escalation and ensure it gets consumed
            test_escalation = generate_test_escalation()
            assert writer.write_escalation(test_escalation)
            read_from_escalation_queue(reader)
            mock_wait_for_connection.assert_called_once()
            mock_consume_escalation.assert_called_once_with(escalation_info_to_str(test_escalation))


def test_queue_management_retries_successfully(
    test_escalation: EscalationInfo, writer: QueueWriter, reader: QueueReader
):
    """Verifies that an error from consumption triggers a retry for the escalation."""

    def side_effect_true_then_false(*args, **kwargs):
        """A side effect function that returns (None, True) when first called and (None, False) on subsequent calls."""
        if not hasattr(side_effect_true_then_false, "called"):
            side_effect_true_then_false.called = True
            return (None, True)
        return (None, False)

    assert writer.write_escalation(test_escalation)
    with patch(
        "app.escalation_queue.manage_reader.consume_queued_escalation", side_effect=side_effect_true_then_false
    ) as mock_consume_escalation:
        with patch("app.escalation_queue.manage_reader.wait_for_connection") as mock_wait_for_connection:
            read_from_escalation_queue(reader)

            expected_connection_calls = [call()] * 2
            assert mock_wait_for_connection.mock_calls == expected_connection_calls

            test_escalation_str = escalation_info_to_str(test_escalation)
            expected_consumption_calls = [call(test_escalation_str)] * 2
            assert mock_consume_escalation.mock_calls == expected_consumption_calls


def test_queue_management_stops_retrying_after_max_attempts(
    test_escalation: EscalationInfo, writer: QueueWriter, reader: QueueReader
):
    """Verifies that an escalation will be attempted to be escalated only up to the max allowed attempts."""
    assert writer.write_escalation(test_escalation)
    with patch(
        "app.escalation_queue.manage_reader.consume_queued_escalation", return_value=(None, True)
    ) as mock_consume_escalation:
        with patch("app.escalation_queue.manage_reader.wait_for_connection") as mock_wait_for_connection:
            read_from_escalation_queue(reader)

            expected_connection_calls = [call()] * MAX_RETRY_ATTEMPTS
            mock_wait_for_connection.assert_has_calls(expected_connection_calls)

            test_escalation_str = escalation_info_to_str(test_escalation)
            expected_consumption_calls = [call(test_escalation_str)] * MAX_RETRY_ATTEMPTS
            mock_consume_escalation.assert_has_calls(expected_consumption_calls)


def test_queue_management_no_retry_when_no_reason_to(
    test_escalation: EscalationInfo, writer: QueueWriter, reader: QueueReader
):
    """Verifies that an escalation is not retried when consumption fails in a way that retrying won't fix."""
    assert writer.write_escalation(test_escalation)
    with patch(
        "app.escalation_queue.manage_reader.consume_queued_escalation", return_value=(None, False)
    ) as mock_consume_escalation:
        with patch("app.escalation_queue.manage_reader.wait_for_connection") as mock_wait_for_connection:
            read_from_escalation_queue(reader)
            mock_wait_for_connection.assert_called_once()
            mock_consume_escalation.assert_called_once()
