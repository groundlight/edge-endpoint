import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator, Iterator
from unittest.mock import Mock, call, patch

import ksuid
import pytest
from fastapi import HTTPException, status
from groundlight import GroundlightClientError
from urllib3.exceptions import MaxRetryError

from app.core.utils import generate_iq_id, get_formatted_timestamp_str
from app.escalation_queue.constants import MAX_QUEUE_FILE_LINES, MAX_RETRY_ATTEMPTS
from app.escalation_queue.manage_reader import consume_queued_escalation, read_from_escalation_queue
from app.escalation_queue.models import EscalationInfo, SubmitImageQueryParams
from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.queue_utils import safe_escalate_with_queue_write, write_escalation_to_queue
from app.escalation_queue.queue_writer import QueueWriter, convert_escalation_info_to_str

### Helper functions


def generate_queue_reader(base_dir: str) -> QueueReader:
    return QueueReader(base_dir)


def generate_queue_writer(base_dir: str) -> QueueWriter:
    return QueueWriter(base_dir)


def generate_test_submit_iq_params() -> SubmitImageQueryParams:
    return SubmitImageQueryParams(
        wait=0,
        patience_time=None,
        confidence_threshold=0.9,
        human_review=None,
        metadata={"test_key": "test_value"},
        image_query_id=generate_iq_id(),
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


def assert_expected_reader_output(reader_iter: QueueReader | Iterator[str], expected_values: list[EscalationInfo]):
    """
    Helper function to assert that the reader produces an expected list of escalations.

    The `reader_iter` argument can be either a QueueReader or an Iterator. The latter case allows previous iteration
    progress to be preserved between calls.
    """
    for value, escalation_str in zip(expected_values, reader_iter):
        assert EscalationInfo(**json.loads(escalation_str)) == value


### Global fixtures


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
def test_base_dir() -> Generator[str, None, None]:
    temp_dir = os.path.join(tempfile.gettempdir(), f"test-escalation-queue-{ksuid.KsuidMs()}")
    os.makedirs(temp_dir, exist_ok=True)
    yield temp_dir
    # Clean up the directory once the test finishes
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def test_writer(test_base_dir: str) -> QueueWriter:
    return generate_queue_writer(base_dir=test_base_dir)


@pytest.fixture
def test_reader(test_base_dir: str) -> QueueReader:
    return generate_queue_reader(base_dir=test_base_dir)


class TestQueueWriter:
    def assert_file_length(self, file_path: str, expected_lines: int):
        """Testing function to assert that the file at the specified file path has the expected number of lines."""
        with open(file_path, "r") as f:
            num_lines = len(f.readlines())
            assert num_lines == expected_lines

    def test_successive_writes_go_to_same_file(self, test_writer: QueueWriter, test_escalation_info: EscalationInfo):
        """Verify that successive escalation writes go to the same file."""
        for i in range(1, 4):
            assert test_writer.write_escalation(test_escalation_info)
            self.assert_file_length(test_writer.last_file_path, i)
            assert test_writer.num_lines_written_to_file == i

    def test_write_to_different_file(self, test_writer: QueueWriter, test_escalation_info: EscalationInfo):
        """Verify that the writer uses a new file when the previous one is gone."""
        assert test_writer.write_escalation(test_escalation_info)
        first_file_path = test_writer.last_file_path
        self.assert_file_length(first_file_path, 1)
        assert test_writer.num_lines_written_to_file == 1

        first_file_path.unlink()
        assert test_writer.write_escalation(test_escalation_info)
        self.assert_file_length(test_writer.last_file_path, 1)
        assert first_file_path != test_writer.last_file_path
        assert test_writer.num_lines_written_to_file == 1

    def test_separate_writers_write_to_different_files(self, test_base_dir: str, test_escalation_info: EscalationInfo):
        """Verify that separate writers will write to separate files."""
        first_writer = generate_queue_writer(test_base_dir)
        second_writer = generate_queue_writer(test_base_dir)
        assert first_writer.write_escalation(test_escalation_info)
        assert second_writer.write_escalation(test_escalation_info)

        assert not first_writer.last_file_path.samefile(second_writer.last_file_path)

        self.assert_file_length(first_writer.last_file_path, 1)
        self.assert_file_length(second_writer.last_file_path, 1)

    def test_writer_respects_file_length_limit(self, test_writer: QueueWriter, test_escalation_info: EscalationInfo):
        """Verify that the writer starts writing to a new file when a file reaches the max allowed line length."""
        for i in range(MAX_QUEUE_FILE_LINES):
            assert test_writer.write_escalation(test_escalation_info)
            self.assert_file_length(test_writer.last_file_path, i + 1)
            assert test_writer.num_lines_written_to_file == i + 1

        first_file_path = test_writer.last_file_path
        assert test_writer.write_escalation(test_escalation_info)
        self.assert_file_length(test_writer.last_file_path, 1)
        assert test_writer.num_lines_written_to_file == 1
        assert not first_file_path.samefile(test_writer.last_file_path)

    def test_writer_can_write_image(self, test_writer: QueueWriter, timestamp_str: str, test_image_bytes: bytes):
        """Verify that basic image writing works properly."""
        detector_id = "test_id"
        image_path = test_writer.write_image_bytes(test_image_bytes, detector_id, timestamp_str)
        assert detector_id in image_path
        assert timestamp_str in image_path

        image_path = Path(image_path)
        assert image_path.is_file()

        saved_bytes = image_path.read_bytes()
        assert saved_bytes == test_image_bytes

    def test_writer_saves_images_to_unique_paths(
        self, test_writer: QueueWriter, timestamp_str: str, test_image_bytes: bytes
    ):
        """Verify that multiple images saved with the same detector ID and timestamp are saved to unique paths."""
        detector_id = "test_id"
        first_image_path = test_writer.write_image_bytes(test_image_bytes, detector_id, timestamp_str)
        first_image_path = Path(first_image_path)
        assert first_image_path.is_file()

        second_image_path = test_writer.write_image_bytes(test_image_bytes, detector_id, timestamp_str)
        second_image_path = Path(second_image_path)
        assert second_image_path.is_file()

        assert not first_image_path.samefile(second_image_path)


class TestQueueReader:
    def test_reader_blocks_until_file_available(
        self, test_escalation_info: EscalationInfo, test_writer: QueueWriter, test_reader: QueueReader
    ):
        """Verify that the reader blocks until a file is available and then reads from it."""
        call_count = 0
        num_wait_calls = 3

        def side_effect(duration: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= num_wait_calls:
                test_writer.write_escalation(test_escalation_info)

        # To prevent indefinite blocking, patch the wait method to write an escalation after being called a certain
        # number of times.
        with patch.object(test_reader, "_wait_for_file_check", side_effect=side_effect) as mock_wait:
            assert_expected_reader_output(test_reader, [test_escalation_info])
            assert mock_wait.call_count == num_wait_calls  # Verify that the reader waited for the specified # of times

    def test_reader_moves_file(
        self, test_reader: QueueReader, test_writer: QueueWriter, test_escalation_info: EscalationInfo
    ):
        """Verify that the reader moves the file being read."""
        assert test_writer.write_escalation(test_escalation_info)
        written_to_path = test_writer.last_file_path

        assert_expected_reader_output(test_reader, [test_escalation_info])
        assert not written_to_path.exists()

    def test_reader_reads_multiple_lines_from_same_file(self, test_reader: QueueReader, test_writer: QueueWriter):
        """
        Verify that the reader can read multiple lines from the same file in the correct order.
        """
        test_escalation_infos = [generate_test_escalation_info(detector_id=f"test_id_{i}") for i in range(3)]

        for escalation_info in test_escalation_infos:
            assert test_writer.write_escalation(escalation_info)

        assert_expected_reader_output(test_reader, test_escalation_infos)

    def test_reader_prioritizes_oldest_file(self, test_base_dir: str, test_reader: QueueReader):
        """Verify that the reader reads from the oldest file first."""
        test_escalation_info_1 = generate_test_escalation_info(detector_id="test_id_1")
        test_escalation_info_2 = generate_test_escalation_info(detector_id="test_id_2")

        first_writer = generate_queue_writer(test_base_dir)
        second_writer = generate_queue_writer(test_base_dir)
        assert first_writer.write_escalation(test_escalation_info_1)
        assert second_writer.write_escalation(test_escalation_info_2)

        assert_expected_reader_output(test_reader, [test_escalation_info_1, test_escalation_info_2])

    def test_reader_deletes_finished_file(self, test_base_dir: str, test_reader: QueueReader):
        """Verify that the reader deletes a file (and associated tracking file) when it reads all the lines from it."""
        test_escalation_info_1 = generate_test_escalation_info(detector_id="test_id_1")
        test_escalation_info_2 = generate_test_escalation_info(detector_id="test_id_2")

        first_writer = generate_queue_writer(test_base_dir)
        second_writer = generate_queue_writer(test_base_dir)
        assert first_writer.write_escalation(test_escalation_info_1)
        assert second_writer.write_escalation(test_escalation_info_2)

        reading_dir = test_reader.base_reading_dir
        assert reading_dir.is_dir() and not any(reading_dir.iterdir())

        num_files_in_pair = 2

        reader_iter = iter(test_reader)  # Reuse the same iterator so we can resume from the same spot
        assert_expected_reader_output(reader_iter, [test_escalation_info_1])
        # Reading directory should contain the first pair of reading and tracking files
        assert len([p for p in reading_dir.iterdir()]) == num_files_in_pair

        assert_expected_reader_output(reader_iter, [test_escalation_info_2])
        # Reading directory should contain the second pair of reading and tracking files
        assert len([p for p in reading_dir.iterdir()]) == num_files_in_pair

    def test_reader_starts_from_correct_intermediate_line(self, test_base_dir: str, test_writer: QueueWriter):
        """Verify that the reader starts at the right spot when resuming from a partially finished file."""
        # Write three unique escalations to a file
        test_escalation_infos = [generate_test_escalation_info(detector_id=f"test_id_{i}") for i in range(3)]
        for escalation_info in test_escalation_infos:
            assert test_writer.write_escalation(escalation_info)

        # Read two lines from the file
        first_reader = generate_queue_reader(test_base_dir)
        assert_expected_reader_output(first_reader, [test_escalation_infos[0], test_escalation_infos[1]])

        # Now a new reader should continue from the 2nd written escalation in the partially-read file,
        # because there's only record of one escalation from that file being finished.
        second_reader = generate_queue_reader(test_base_dir)
        assert_expected_reader_output(second_reader, [test_escalation_infos[1], test_escalation_infos[2]])

    def test_reader_resumes_multiple_times_correctly(self, test_base_dir: str, test_writer: QueueWriter):
        """Verify that the reader can resume from a file multiple times, and start from the proper place each time."""
        # Write six unique escalations to a file
        test_escalation_infos = [generate_test_escalation_info(detector_id=f"test_id_{i}") for i in range(6)]
        for escalation_info in test_escalation_infos:
            assert test_writer.write_escalation(escalation_info)

        # Read the first two lines from the file
        first_reader = generate_queue_reader(test_base_dir)
        assert_expected_reader_output(first_reader, [test_escalation_infos[0], test_escalation_infos[1]])

        # Now a new reader should continue from the 2nd written escalation in the partially-read file
        second_reader = generate_queue_reader(test_base_dir)
        assert_expected_reader_output(second_reader, [test_escalation_infos[1], test_escalation_infos[2]])

        # Now a new reader should continue from the 3rd written escalation in the partially-read file
        third_reader = generate_queue_reader(test_base_dir)
        assert_expected_reader_output(third_reader, [test_escalation_infos[2], test_escalation_infos[3]])

    def test_reader_prioritizes_tracking_file(self, test_base_dir: str):
        """Verify that the reader chooses a tracking file over a normal written file when there's one available."""
        # Write three escalations to a file
        test_escalation_info_1 = generate_test_escalation_info(detector_id="test_id_1")
        first_writer = generate_queue_writer(test_base_dir)
        for _ in range(3):
            assert first_writer.write_escalation(test_escalation_info_1)
        # Read two lines from the file
        first_reader = generate_queue_reader(test_base_dir)
        assert_expected_reader_output(first_reader, [test_escalation_info_1] * 2)

        # Create a new written file
        test_escalation_info_2 = generate_test_escalation_info(detector_id="test_id_2")
        second_writer = generate_queue_writer(test_base_dir)
        assert second_writer.write_escalation(test_escalation_info_2)

        # Ensure a new reader will read from the in progress file before the newly written file
        second_reader = generate_queue_reader(test_base_dir)
        assert_expected_reader_output(second_reader, [test_escalation_info_1] * 2 + [test_escalation_info_2])

    def test_reader_selects_empty_tracking_file(self, test_base_dir: str, test_writer: QueueWriter):
        """Verify that the reader will select a tracking file even if it contains no tracked escalations."""
        test_escalation_info_1 = generate_test_escalation_info(detector_id="test_id_1")
        assert test_writer.write_escalation(test_escalation_info_1)
        first_reader = generate_queue_reader(test_base_dir)
        assert_expected_reader_output(first_reader, [test_escalation_info_1])

        # Now there should be an empty tracking file created by the first reader, which the second reader should select
        test_escalation_info_2 = generate_test_escalation_info(detector_id="test_id_2")
        assert test_writer.write_escalation(test_escalation_info_2)
        second_reader = generate_queue_reader(test_base_dir)
        assert_expected_reader_output(second_reader, [test_escalation_info_1, test_escalation_info_2])


class TestConsumeQueuedEscalation:
    def test_consume_escalation_successful(self, test_escalation_info: EscalationInfo):
        """Verifies that basic escalation consumption is successful."""
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)
        mock_gl = Mock()
        mock_gl.get_image_query.side_effect = HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=mock_gl)
        assert escalation_result is not None
        assert not should_try_again

    def test_consume_escalation_image_not_found(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and the escalation is skipped when the image cannot be found."""
        test_escalation_info.image_path_str = "not-a-real-path"
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)

        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
        assert escalation_result is None
        assert not should_try_again

    def test_consume_escalation_no_connection(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and a retry is prompted when there is no connection."""
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)

        # No connection when calling get_image_query
        mock_gl = Mock()
        mock_gl.get_image_query.side_effect = MaxRetryError(pool=None, url=None)
        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=mock_gl)
        assert escalation_result is None
        assert should_try_again

        # No connection when calling submit_image_query
        mock_gl = Mock()
        mock_gl.get_image_query.side_effect = HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        mock_gl.submit_image_query.side_effect = MaxRetryError(pool=None, url=None)
        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=mock_gl)
        assert escalation_result is None
        assert should_try_again

    def test_consume_escalation_bad_request(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and no retry is prompted when a bad request exception is encountered."""
        test_escalation_info.submit_iq_params.human_review = "NOT A VALID OPTION"
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)
        with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()) as mock_sdk_call:
            mock_sdk_call.side_effect = HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
            escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
            assert escalation_result is None
            assert not should_try_again

    def test_consume_escalation_other_http_exception(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and a retry is prompted when any non-handled HTTP exception is encountered."""
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)
        with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=Mock()) as mock_sdk_call:
            mock_sdk_call.side_effect = HTTPException(status_code=status.HTTP_418_IM_A_TEAPOT)
            escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=Mock())
            assert escalation_result is None
            assert should_try_again

    def test_consume_escalation_gl_client_creation_failure(self, test_escalation_info: EscalationInfo):
        """Verifies that no error is raised and a retry is prompted when it fails to create a Groundlight client."""
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)

        with patch("app.escalation_queue.manage_reader._groundlight_client", return_value=Mock()) as mock_gl_client:
            mock_gl_client.side_effect = GroundlightClientError()
            escalation_result, should_try_again = consume_queued_escalation(test_escalation_str)
            assert escalation_result is None
            assert should_try_again

    def test_consume_escalation_iq_id_already_exists_in_cloud(self, test_escalation_info: EscalationInfo):
        """Verifies that if the image query ID already exists in the cloud, no escalation is done."""
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)
        mock_gl = Mock()
        mock_get_image_query: Mock = mock_gl.get_image_query
        mock_submit_image_query: Mock = mock_gl.submit_image_query

        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=mock_gl)
        assert escalation_result is None
        assert not should_try_again

        mock_get_image_query.assert_called_once_with(id=test_escalation_info.submit_iq_params.image_query_id)
        mock_submit_image_query.assert_not_called()

    def test_consume_escalation_iq_id_does_not_exist_in_cloud(self, test_escalation_info: EscalationInfo):
        """Verifies that if the image query ID does not already exist in the cloud, escalation proceeds normally."""
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)
        mock_gl = Mock()
        mock_get_image_query: Mock = mock_gl.get_image_query
        mock_get_image_query.side_effect = HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        mock_submit_image_query: Mock = mock_gl.submit_image_query

        escalation_result, should_try_again = consume_queued_escalation(test_escalation_str, gl=mock_gl)
        assert escalation_result is not None
        assert not should_try_again

        mock_get_image_query.assert_called_once_with(id=test_escalation_info.submit_iq_params.image_query_id)
        mock_submit_image_query.assert_called_once()


class TestReadFromEscalationQueue:
    @pytest.fixture
    def mock_consume_escalation(self):
        """
        Mocks the consume_queued_escalation function in manage_reader.py.
        Including this fixture in a test will automatically apply the patch.
        """
        with patch(
            "app.escalation_queue.manage_reader.consume_queued_escalation",
        ) as consume_mock:
            yield consume_mock

    @pytest.fixture
    def mock_wait_for_connection(self):
        """
        Mocks the wait_for_network_connection function in manage_reader.py.
        Including this fixture in a test will automatically apply the patch.
        """
        with patch("app.escalation_queue.manage_reader.wait_for_network_connection") as wait_mock:
            yield wait_mock

    def test_queue_management_basic_functionality(
        self,
        test_writer: QueueWriter,
        test_reader: QueueReader,
        mock_consume_escalation: Mock,
        mock_wait_for_connection: Mock,
    ):
        """Verifies that basic queue management works when reading from the queue and consuming the queued escalations."""
        # Starts off with nothing in the queue to read
        read_from_escalation_queue(test_reader)
        mock_wait_for_connection.assert_not_called()
        mock_consume_escalation.assert_not_called()
        mock_wait_for_connection.reset_mock()
        mock_consume_escalation.reset_mock()
        assert test_reader._get_num_tracked_escalations() == 0

        num_escalations = 3
        test_escalation_infos = [
            generate_test_escalation_info(detector_id=f"test_id_{i}") for i in range(num_escalations)
        ]
        for escalation_info in test_escalation_infos:
            assert test_writer.write_escalation(escalation_info)

        mock_consume_escalation.return_value = (Mock(), False)

        # Ensure the escalations we wrote get consumed
        for i, escalation_info in enumerate(test_escalation_infos):
            read_from_escalation_queue(test_reader)
            mock_wait_for_connection.assert_called_once()
            mock_consume_escalation.assert_called_once_with(convert_escalation_info_to_str(escalation_info))
            mock_wait_for_connection.reset_mock()
            mock_consume_escalation.reset_mock()
            assert test_reader._get_num_tracked_escalations() == i

        # Nothing more in the queue to read
        read_from_escalation_queue(test_reader)
        mock_wait_for_connection.assert_not_called()
        mock_consume_escalation.assert_not_called()
        mock_wait_for_connection.reset_mock()
        mock_consume_escalation.reset_mock()
        assert test_reader._get_num_tracked_escalations() == 0

        # Write another escalation and ensure it gets consumed
        test_escalation_info = generate_test_escalation_info()
        assert test_writer.write_escalation(test_escalation_info)
        read_from_escalation_queue(test_reader)
        mock_wait_for_connection.assert_called_once()
        mock_consume_escalation.assert_called_once_with(convert_escalation_info_to_str(test_escalation_info))
        assert test_reader._get_num_tracked_escalations() == 0  # TODO this is confusing

    def test_queue_management_retries_successfully(
        self,
        test_escalation_info: EscalationInfo,
        test_writer: QueueWriter,
        test_reader: QueueReader,
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

        assert test_writer.write_escalation(test_escalation_info)

        read_from_escalation_queue(test_reader)

        num_attempts = 2
        assert len(mock_wait_for_connection.mock_calls) == num_attempts
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)
        expected_consumption_calls = [call(test_escalation_str)] * num_attempts
        assert mock_consume_escalation.mock_calls == expected_consumption_calls

    def test_queue_management_stops_retrying_after_max_attempts(
        self,
        test_escalation_info: EscalationInfo,
        test_writer: QueueWriter,
        test_reader: QueueReader,
        mock_consume_escalation: Mock,
        mock_wait_for_connection: Mock,
    ):
        """Verifies that an escalation will be attempted to be escalated only up to the max allowed attempts."""
        assert test_writer.write_escalation(test_escalation_info)
        mock_consume_escalation.return_value = (None, True)
        read_from_escalation_queue(test_reader)

        assert len(mock_wait_for_connection.mock_calls) == MAX_RETRY_ATTEMPTS
        test_escalation_str = convert_escalation_info_to_str(test_escalation_info)
        expected_consumption_calls = [call(test_escalation_str)] * MAX_RETRY_ATTEMPTS
        assert mock_consume_escalation.mock_calls == expected_consumption_calls

    def test_queue_management_no_retry_when_no_reason_to(
        self,
        test_escalation_info: EscalationInfo,
        test_writer: QueueWriter,
        test_reader: QueueReader,
        mock_consume_escalation: Mock,
        mock_wait_for_connection: Mock,
    ):
        """Verifies that an escalation is not retried when consumption fails in a way that retrying won't fix."""
        assert test_writer.write_escalation(test_escalation_info)
        mock_consume_escalation.return_value = (None, False)
        read_from_escalation_queue(test_reader)
        mock_wait_for_connection.assert_called_once()
        mock_consume_escalation.assert_called_once()


class TestQueueUtils:
    @pytest.fixture
    def test_submit_iq_params(self) -> SubmitImageQueryParams:
        return generate_test_submit_iq_params()

    def test_write_escalation_to_queue_successful(
        self,
        test_writer: QueueWriter,
        test_reader: QueueReader,
        test_escalation_info: EscalationInfo,
        test_image_bytes: bytes,
        test_submit_iq_params: SubmitImageQueryParams,
    ):
        write_escalation_to_queue(
            test_writer, test_escalation_info.detector_id, test_image_bytes, test_submit_iq_params
        )

        next_escalation_info = EscalationInfo(**json.loads(next(iter(test_reader))))
        assert next_escalation_info.detector_id == test_escalation_info.detector_id
        assert next_escalation_info.submit_iq_params == test_submit_iq_params
        assert Path(next_escalation_info.image_path_str).read_bytes() == test_image_bytes

    def test_write_escalation_to_queue_failure_with_retry(
        self,
    ):
        # TODO after implementing retry
        pass

    def test_safe_escalate_with_queue_write_successful_request(
        self, test_writer: QueueWriter, test_image_bytes: bytes, test_escalation_info: EscalationInfo
    ):
        """Verifies that safe_escalate_with_queue_write makes the correct SDK call when there's no exception."""
        mock_gl = Mock()
        mock_submit_image_query: Mock = mock_gl.submit_image_query
        safe_escalate_with_queue_write(
            gl=mock_gl,
            queue_writer=test_writer,
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
        self, test_writer: QueueWriter, test_image_bytes: bytes, test_escalation_info: EscalationInfo
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
                    queue_writer=test_writer,
                    detector_id=test_escalation_info.detector_id,
                    image_bytes=test_image_bytes,
                    want_async=False,
                    submit_iq_params=test_escalation_info.submit_iq_params,
                )

            mock_write_escalation_to_queue.assert_called_once_with(
                writer=test_writer, image_bytes=test_image_bytes, submit_iq_params=test_escalation_info.submit_iq_params
            )
