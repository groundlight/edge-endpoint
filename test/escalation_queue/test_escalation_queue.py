import json
import os
import re
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
from app.escalation_queue.models import EscalationInfo, SubmitImageQueryParams
from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.queue_utils import safe_escalate_with_queue_write, write_escalation_to_queue
from app.escalation_queue.queue_writer import QueueWriter

### Helper functions


def generate_test_submit_iq_params() -> SubmitImageQueryParams:
    return SubmitImageQueryParams(
        wait=0,
        patience_time=None,
        confidence_threshold=0.9,
        human_review=None,
        metadata={"test_key": "test_value"},
    )


def generate_test_escalation_info(
    timestamp_str: str = get_formatted_timestamp_str(),
    submit_iq_params: SubmitImageQueryParams = generate_test_submit_iq_params(),
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


def escalation_info_to_str(escalation_info: EscalationInfo) -> str:
    return f"{json.dumps(escalation_info.model_dump())}\n"


def assert_correct_reader_tracking_format(reader: QueueReader) -> None:
    """Assert that the reader's tracking file is formatted correctly. Passes if there is no such file."""
    if reader.current_tracking_file_path is not None:
        with reader.current_tracking_file_path.open(mode="r") as f:
            lines = f.readlines()
            if len(lines) >= 1:  # If there's at least one line in the file...
                assert len(lines) == 1  # then there should be exactly one.
                pattern = r"^1*$"  # The line should consist of any number of 1s
                assert re.fullmatch(pattern, lines[0]) is not None, (
                    f"The tracking file line: {lines[0]} did not match the expected pattern."
                )


def get_num_tracked_escalations(reader: QueueReader) -> int:
    """
    Get the number of escalations recorded in the reader's tracking file.
    Returns 0 if there is no such file. Otherwise, returns the number of escalations as an int.
    """
    if reader.current_tracking_file_path is None:
        return 0
    with reader.current_tracking_file_path.open(mode="r") as f:
        line = f.readline()
        return len(line)


### Fixtures


@pytest.fixture
def timestamp_str() -> str:
    return get_formatted_timestamp_str()


@pytest.fixture
def test_image_bytes() -> bytes:
    image_path = Path("test/assets/cat.jpeg")
    return image_path.read_bytes()


@pytest.fixture
def test_escalation_info() -> EscalationInfo:
    return generate_test_escalation_info()


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


class TestQueueWriter:
    def assert_file_length(self, file_path: str, expected_lines: int):
        """Assert that the file at the specified file path has the expected number of lines."""
        with open(file_path, "r") as f:
            num_lines = len(f.readlines())
            assert num_lines == expected_lines

    def test_successive_writes_go_to_same_file(self, writer: QueueWriter, test_escalation_info: EscalationInfo):
        """Verify that successive escalation writes go to the same file."""
        for i in range(1, 4):
            assert writer.write_escalation(test_escalation_info)
            self.assert_file_length(writer.last_file_path, i)
            assert writer.num_lines_written_to_file == i

    def test_write_to_different_file(self, writer: QueueWriter, test_escalation_info: EscalationInfo):
        """Verify that the writer uses a new file when the previous one is gone."""
        assert writer.write_escalation(test_escalation_info)
        first_file_path = writer.last_file_path
        self.assert_file_length(first_file_path, 1)
        assert writer.num_lines_written_to_file == 1

        first_file_path.unlink()
        assert writer.write_escalation(test_escalation_info)
        self.assert_file_length(writer.last_file_path, 1)
        assert first_file_path != writer.last_file_path
        assert writer.num_lines_written_to_file == 1

    def test_separate_writers_write_to_different_files(
        self, writer: QueueWriter, second_writer: QueueWriter, test_escalation_info: EscalationInfo
    ):
        """Verify that separate writers will write to separate files."""
        assert writer.write_escalation(test_escalation_info)
        assert second_writer.write_escalation(test_escalation_info)

        assert not writer.last_file_path.samefile(second_writer.last_file_path)

        self.assert_file_length(writer.last_file_path, 1)
        self.assert_file_length(second_writer.last_file_path, 1)

    def test_writer_respects_file_length_limit(self, writer: QueueWriter, test_escalation_info: EscalationInfo):
        """Verify that the writer starts writing to a new file when a file reaches the max allowed line length."""
        for i in range(MAX_QUEUE_FILE_LINES):
            assert writer.write_escalation(test_escalation_info)
            self.assert_file_length(writer.last_file_path, i + 1)
            assert writer.num_lines_written_to_file == i + 1

        first_file_path = writer.last_file_path
        assert writer.write_escalation(test_escalation_info)
        self.assert_file_length(writer.last_file_path, 1)
        assert writer.num_lines_written_to_file == 1
        assert not first_file_path.samefile(writer.last_file_path)

    def test_writer_can_write_image(self, writer: QueueWriter, timestamp_str: str, test_image_bytes: bytes):
        """Verify that basic image writing works properly."""
        detector_id = "test_id"
        image_path = writer.write_image_bytes(test_image_bytes, detector_id, timestamp_str)
        assert detector_id in image_path
        assert timestamp_str in image_path

        image_path = Path(image_path)
        assert image_path.is_file()

        saved_bytes = image_path.read_bytes()
        assert saved_bytes == test_image_bytes

    def test_writer_saves_images_to_unique_paths(
        self, writer: QueueWriter, timestamp_str: str, test_image_bytes: bytes
    ):
        """Verify that multiple images saved with the same detector ID and timestamp are saved to unique paths."""
        detector_id = "test_id"
        first_image_path = writer.write_image_bytes(test_image_bytes, detector_id, timestamp_str)
        first_image_path = Path(first_image_path)
        assert first_image_path.is_file()

        second_image_path = writer.write_image_bytes(test_image_bytes, detector_id, timestamp_str)
        second_image_path = Path(second_image_path)
        assert second_image_path.is_file()

        assert not first_image_path.samefile(second_image_path)


class TestQueueReader:
    def assert_contents_of_next_read_line(
        self, reader: QueueReader, expected_result: EscalationInfo | None
    ) -> None:  # TODO rename
        """Assert that the next read line matches the expected result."""
        next_escalation_str = reader.get_next_line()
        next_escalation = None if next_escalation_str is None else EscalationInfo(**json.loads(next_escalation_str))
        assert next_escalation == expected_result

    def test_read_with_empty_queue(self, reader: QueueReader):
        """Verify that the reader always returns None when there is nothing in the queue."""
        for _ in range(5):
            self.assert_contents_of_next_read_line(reader, None)

    def test_reader_moves_file(self, reader: QueueReader, writer: QueueWriter, test_escalation_info: EscalationInfo):
        """Verify that the reader moves the file being read."""
        assert writer.write_escalation(test_escalation_info)
        written_to_path = writer.last_file_path

        self.assert_contents_of_next_read_line(reader, test_escalation_info)

        assert reader.current_reading_file_path != written_to_path
        assert not written_to_path.exists()

    def test_reader_finds_new_file(
        self, reader: QueueReader, writer: QueueWriter, test_escalation_info: EscalationInfo
    ):
        """Verify that the reader can find and read from a file created after the reader was instantiated."""
        assert writer.write_escalation(test_escalation_info)
        first_written_path = writer.last_file_path

        self.assert_contents_of_next_read_line(reader, test_escalation_info)

        assert writer.write_escalation(test_escalation_info)
        second_written_path = writer.last_file_path
        assert first_written_path != second_written_path  # Wrote to a different file

        self.assert_contents_of_next_read_line(reader, test_escalation_info)

    def test_read_multiple_lines_from_same_file(self, reader: QueueReader, writer: QueueWriter):
        """
        Verify that the reader can read multiple lines from the same file in the correct order, and returns None when there
        are none left.
        """
        num_lines = 3
        test_escalations = [generate_test_escalation_info(detector_id=f"test_id_{i}") for i in range(num_lines)]

        for escalation in test_escalations:
            assert writer.write_escalation(escalation)

        for escalation in test_escalations:
            self.assert_contents_of_next_read_line(reader, escalation)
        self.assert_contents_of_next_read_line(reader, None)

    def test_reader_selects_oldest_file(self, reader: QueueReader, writer: QueueWriter, second_writer: QueueWriter):
        """Verify that the reader reads from the oldest file first."""
        test_escalation_1 = generate_test_escalation_info(detector_id="test_id_1")
        test_escalation_2 = generate_test_escalation_info(detector_id="test_id_2")

        assert writer.write_escalation(test_escalation_1)
        assert second_writer.write_escalation(test_escalation_2)
        assert not writer.last_file_path.samefile(second_writer.last_file_path)

        self.assert_contents_of_next_read_line(reader, test_escalation_1)
        self.assert_contents_of_next_read_line(reader, test_escalation_2)

    def test_reader_deletes_empty_file(
        self, reader: QueueReader, writer: QueueWriter, test_escalation_info: EscalationInfo
    ):
        """Verify that the reader deletes a file when it reads all the lines from it."""
        num_lines = 3
        for _ in range(num_lines):
            assert writer.write_escalation(test_escalation_info)

        for _ in range(num_lines):
            self.assert_contents_of_next_read_line(reader, test_escalation_info)

        previous_reading_path = reader.current_reading_file_path
        assert previous_reading_path is not None

        self.assert_contents_of_next_read_line(reader, None)
        assert reader.current_reading_file_path is None
        assert not previous_reading_path.exists()

    def test_reader_basic_tracking(
        self, reader: QueueReader, writer: QueueWriter, test_escalation_info: EscalationInfo
    ):
        """Verify that the reader tracks escalations in a separate file properly."""
        num_lines = 3
        for _ in range(num_lines):
            assert writer.write_escalation(test_escalation_info)

        assert get_num_tracked_escalations(reader) == 0

        for i in range(num_lines):
            self.assert_contents_of_next_read_line(reader, test_escalation_info)
            assert_correct_reader_tracking_format(reader)
            assert (
                get_num_tracked_escalations(reader) == i
            )  # Lags one behind because it only writes to the tracking file on the next read

        self.assert_contents_of_next_read_line(reader, None)
        assert reader.current_tracking_file_path is None
        assert get_num_tracked_escalations(reader) == 0


class TestConsumeQueuedEscalation:
    def test_consume_escalation_successful(self, test_escalation_info: EscalationInfo):
        """Verifies that basic escalation consumption is successful."""
        test_escalation_str = escalation_info_to_str(test_escalation_info)
        with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()):
            escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
            assert escalation_result is not None
            assert not should_try_again

    def test_consume_escalation_image_not_found(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and the escalation is skipped when the image cannot be found."""
        test_escalation_info.image_path_str = "not-a-real-path"
        test_escalation_str = escalation_info_to_str(test_escalation_info)

        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
        assert escalation_result is None
        assert not should_try_again

    def test_consume_escalation_no_connection(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and a retry is prompted when there is no connection."""
        test_escalation_str = escalation_info_to_str(test_escalation_info)
        with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()) as mock_sdk_call:
            mock_sdk_call.side_effect = MaxRetryError(pool=None, url=None)
            escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
            assert escalation_result is None
            assert should_try_again

    def test_consume_escalation_bad_request(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and no retry is prompted when a bad request exception is encountered."""
        test_escalation_info.submit_iq_params.human_review = "NOT A VALID OPTION"
        test_escalation_str = escalation_info_to_str(test_escalation_info)
        with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()) as mock_sdk_call:
            mock_sdk_call.side_effect = HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
            escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
            assert escalation_result is None
            assert not should_try_again

    def test_consume_escalation_other_http_exception(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and a retry is prompted when any non-handled HTTP exception is encountered."""
        test_escalation_str = escalation_info_to_str(test_escalation_info)
        with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()) as mock_sdk_call:
            mock_sdk_call.side_effect = HTTPException(status_code=status.HTTP_418_IM_A_TEAPOT)
            escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
            assert escalation_result is None
            assert should_try_again

    def test_consume_escalation_gl_client_creation_failure(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and a retry is prompted when it fails to create a Groundlight client."""
        test_escalation_str = escalation_info_to_str(test_escalation_info)

        with patch("app.escalation_queue.manage_reader._groundlight_client", return_value=Mock()) as mock_gl_client:
            mock_gl_client.side_effect = GroundlightClientError()
            escalation_result, should_try_again = consume_queued_escalation(test_escalation_str)
            assert escalation_result is None
            assert should_try_again


class TestReadFromEscalationQueue:
    @pytest.fixture
    def mock_consume_escalation(self):
        with patch(
            "app.escalation_queue.manage_reader.consume_queued_escalation",
        ) as consume_mock:
            yield consume_mock

    @pytest.fixture
    def mock_wait_for_connection(self):
        with patch("app.escalation_queue.manage_reader.wait_for_network_connection") as wait_mock:
            yield wait_mock

    def test_queue_management_basic_functionality(
        self, writer: QueueWriter, reader: QueueReader, mock_consume_escalation: Mock, mock_wait_for_connection: Mock
    ):
        """Verifies that basic queue management works when reading from the queue and consuming the queued escalations."""
        # Starts off with nothing in the queue to read
        read_from_escalation_queue(reader)
        mock_wait_for_connection.assert_not_called()
        mock_consume_escalation.assert_not_called()
        mock_wait_for_connection.reset_mock()
        mock_consume_escalation.reset_mock()
        assert_correct_reader_tracking_format(reader)
        assert get_num_tracked_escalations(reader) == 0

        num_escalations = 3
        test_escalation_infos = [
            generate_test_escalation_info(detector_id=f"test_id_{i}") for i in range(num_escalations)
        ]
        for escalation_info in test_escalation_infos:
            assert writer.write_escalation(escalation_info)

        mock_consume_escalation.return_value = (Mock(), False)

        # Ensure the escalations we wrote get consumed
        for i, escalation_info in enumerate(test_escalation_infos):
            read_from_escalation_queue(reader)
            mock_wait_for_connection.assert_called_once()
            mock_consume_escalation.assert_called_once_with(escalation_info_to_str(escalation_info))
            mock_wait_for_connection.reset_mock()
            mock_consume_escalation.reset_mock()
            assert_correct_reader_tracking_format(reader)
            assert get_num_tracked_escalations(reader) == i

        # Nothing more in the queue to read
        read_from_escalation_queue(reader)
        mock_wait_for_connection.assert_not_called()
        mock_consume_escalation.assert_not_called()
        mock_wait_for_connection.reset_mock()
        mock_consume_escalation.reset_mock()
        assert_correct_reader_tracking_format(reader)
        assert get_num_tracked_escalations(reader) == 0

        # Write another escalation and ensure it gets consumed
        test_escalation_info = generate_test_escalation_info()
        assert writer.write_escalation(test_escalation_info)
        read_from_escalation_queue(reader)
        mock_wait_for_connection.assert_called_once()
        mock_consume_escalation.assert_called_once_with(escalation_info_to_str(test_escalation_info))
        assert_correct_reader_tracking_format(reader)
        assert get_num_tracked_escalations(reader) == 0  # TODO this is confusing

    def test_queue_management_retries_successfully(
        self,
        test_escalation_info: EscalationInfo,
        writer: QueueWriter,
        reader: QueueReader,
        mock_consume_escalation: Mock,
        mock_wait_for_connection: Mock,
    ):
        """Verifies that an error from consumption triggers a retry for the escalation."""

        def side_effect_true_then_false(*args, **kwargs):
            """A side effect function that returns (None, True) when first called and (None, False) on subsequent calls."""
            if not hasattr(side_effect_true_then_false, "called"):
                side_effect_true_then_false.called = True
                return (None, True)
            return (None, False)

        mock_consume_escalation.side_effect = side_effect_true_then_false

        assert writer.write_escalation(test_escalation_info)

        read_from_escalation_queue(reader)

        num_attempts = 2
        assert len(mock_wait_for_connection.mock_calls) == num_attempts
        test_escalation_str = escalation_info_to_str(test_escalation_info)
        expected_consumption_calls = [call(test_escalation_str)] * num_attempts
        assert mock_consume_escalation.mock_calls == expected_consumption_calls

    def test_queue_management_stops_retrying_after_max_attempts(
        self,
        test_escalation_info: EscalationInfo,
        writer: QueueWriter,
        reader: QueueReader,
        mock_consume_escalation: Mock,
        mock_wait_for_connection: Mock,
    ):
        """Verifies that an escalation will be attempted to be escalated only up to the max allowed attempts."""
        assert writer.write_escalation(test_escalation_info)
        mock_consume_escalation.return_value = (None, True)
        read_from_escalation_queue(reader)

        assert len(mock_wait_for_connection.mock_calls) == MAX_RETRY_ATTEMPTS
        test_escalation_str = escalation_info_to_str(test_escalation_info)
        expected_consumption_calls = [call(test_escalation_str)] * MAX_RETRY_ATTEMPTS
        assert mock_consume_escalation.mock_calls == expected_consumption_calls

    def test_queue_management_no_retry_when_no_reason_to(
        self,
        test_escalation_info: EscalationInfo,
        writer: QueueWriter,
        reader: QueueReader,
        mock_consume_escalation: Mock,
        mock_wait_for_connection: Mock,
    ):
        """Verifies that an escalation is not retried when consumption fails in a way that retrying won't fix."""
        assert writer.write_escalation(test_escalation_info)
        mock_consume_escalation.return_value = (None, False)
        read_from_escalation_queue(reader)
        mock_wait_for_connection.assert_called_once()
        mock_consume_escalation.assert_called_once()


class TestQueueUtils:
    @pytest.fixture
    def test_submit_iq_params(self) -> SubmitImageQueryParams:
        return generate_test_submit_iq_params()

    def test_write_escalation_to_queue_successful(
        self,
        writer: QueueWriter,
        reader: QueueReader,
        test_escalation_info: EscalationInfo,
        test_image_bytes: bytes,
        test_submit_iq_params: SubmitImageQueryParams,
    ):
        write_escalation_to_queue(writer, test_escalation_info.detector_id, test_image_bytes, test_submit_iq_params)

        next_escalation_str = reader.get_next_line()
        assert next_escalation_str is not None
        next_escalation = EscalationInfo(**json.loads(next_escalation_str))
        assert next_escalation.detector_id == test_escalation_info.detector_id
        assert next_escalation.submit_iq_params == test_submit_iq_params
        assert Path(next_escalation.image_path_str).read_bytes() == test_image_bytes

    def test_write_escalation_to_queue_failure_with_retry(
        self,
    ):
        # TODO after implementing retry
        pass

    def test_safe_escalate_with_queue_write_successful_request(
        self, writer: QueueWriter, test_image_bytes: bytes, test_escalation_info: EscalationInfo
    ):
        """Verifies that safe_escalate_with_queue_write makes the correct SDK call when there's no exception."""
        mock_gl = Mock()
        mock_submit_image_query: Mock = mock_gl.submit_image_query
        safe_escalate_with_queue_write(
            gl=mock_gl,
            queue_writer=writer,
            detector_id=test_escalation_info.detector_id,
            image_bytes=test_image_bytes,
            want_async=False,
            submit_iq_params=test_escalation_info.submit_iq_params,
        )
        mock_submit_image_query.assert_called_once_with(
            detector=test_escalation_info.detector_id,
            image=test_image_bytes,
            want_async=False,
            wait=0,
            patience_time=test_escalation_info.submit_iq_params.patience_time,
            confidence_threshold=test_escalation_info.submit_iq_params.confidence_threshold,
            human_review=test_escalation_info.submit_iq_params.human_review,
            metadata=test_escalation_info.submit_iq_params.metadata,
        )

    def test_safe_escalate_with_queue_write_properly_writes_on_failure(
        self, writer: QueueWriter, test_image_bytes: bytes, test_escalation_info: EscalationInfo
    ):
        """
        Verifies that safe_escalate_with_queue_write catches an exception from the SDK call and writes to the queue.
        """
        mock_gl = Mock()
        mock_submit_image_query: Mock = mock_gl.submit_image_query
        mock_submit_image_query.side_effect = Exception()
        with patch("app.escalation_queue.queue_utils.write_escalation_to_queue") as mock_write_escalation_to_queue:
            with pytest.raises(Exception):
                safe_escalate_with_queue_write(
                    gl=mock_gl,
                    queue_writer=writer,
                    detector_id=test_escalation_info.detector_id,
                    image_bytes=test_image_bytes,
                    want_async=False,
                    submit_iq_params=test_escalation_info.submit_iq_params,
                )

            mock_write_escalation_to_queue.assert_called_once_with(
                writer=writer, image_bytes=test_image_bytes, submit_iq_params=test_escalation_info.submit_iq_params
            )
