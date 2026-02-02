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

from app.core.utils import generate_iq_id, generate_request_id, get_formatted_timestamp_str
from app.escalation_queue.constants import MAX_QUEUE_FILE_LINES
from app.escalation_queue.dropped_escalations import DroppedEscalationReason
from app.escalation_queue.manage_reader import (
    RETRY_WAIT_TIMES,
    _escalate_once,
    consume_queued_escalation,
    read_from_escalation_queue,
)
from app.escalation_queue.models import EscalationInfo, SubmitImageQueryParams
from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.queue_utils import (
    safe_escalate_with_queue_write,
    write_escalation_to_queue,
)
from app.escalation_queue.queue_writer import QueueWriter, convert_escalation_info_to_str
from app.escalation_queue.request_cache import RequestCache

### Helper functions


def generate_queue_reader(base_dir: str) -> QueueReader:
    return QueueReader(base_dir)


def generate_queue_writer(base_dir: str) -> QueueWriter:
    return QueueWriter(base_dir)


def generate_test_submit_iq_params() -> SubmitImageQueryParams:
    return SubmitImageQueryParams(
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
    request_id: str = generate_request_id(),
) -> EscalationInfo:
    data = {
        "timestamp": timestamp_str,
        "detector_id": detector_id,
        "image_path_str": image_path,
        "submit_iq_params": submit_iq_params,
        "request_id": request_id,
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
def test_request_id() -> str:
    return generate_request_id()


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


@pytest.fixture
def test_request_cache(test_base_dir: str) -> RequestCache:
    return RequestCache(test_base_dir)


@pytest.fixture
def escalation_str() -> str:
    return convert_escalation_info_to_str(generate_test_escalation_info())


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


class TestEscalateOnce:
    @pytest.fixture
    def mock_gl(self):
        with patch("app.escalation_queue.manage_reader._groundlight_client") as mock_gl:
            mock_gl.return_value = Mock()
            yield mock_gl.return_value

    def test_successful_escalation(self, test_escalation_info: EscalationInfo, mock_gl: Mock):
        """On a successful escalation, _escalate_once should return the result and not request a retry."""
        dummy_iq = Mock()

        with patch("app.escalation_queue.manage_reader.safe_call_sdk", return_value=dummy_iq) as mock_safe_call_sdk:
            escalation_result, should_try_again, reason, error = _escalate_once(
                test_escalation_info, submit_iq_request_timeout_s=5
            )

            assert escalation_result is dummy_iq
            assert not should_try_again
            assert reason is None
            assert error is None

            mock_safe_call_sdk.assert_called_once()
            first_call_args, _ = mock_safe_call_sdk.call_args
            assert first_call_args[0] is mock_gl.submit_image_query

    def test_image_not_found(self, test_escalation_info: EscalationInfo, mock_gl: Mock):
        """If the image path does not exist, _escalate_once should skip escalation and not retry."""
        test_escalation_info.image_path_str = "this-path-does-not-exist.jpeg"
        result, should_retry, reason, _ = _escalate_once(test_escalation_info, submit_iq_request_timeout_s=5)

        assert result is None
        assert not should_retry
        assert reason == DroppedEscalationReason.IMAGE_NOT_FOUND

    def test_no_connection_during_submit(self, test_escalation_info: EscalationInfo, mock_gl: Mock):
        """If submitting the IQ fails due to connection problems, _escalate_once should suggest a retry."""
        mock_gl.submit_image_query.side_effect = MaxRetryError(pool=None, url=None)
        result, should_retry, _, _ = _escalate_once(test_escalation_info, submit_iq_request_timeout_s=5)

        assert result is None
        assert should_retry

    def test_400_exception(self, test_escalation_info: EscalationInfo, mock_gl: Mock):
        """HTTP 400 exceptions should not trigger a retry. This includes if the IQ already exists in the cloud."""
        mock_gl.submit_image_query.side_effect = HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        result, should_retry, reason, _ = _escalate_once(test_escalation_info, submit_iq_request_timeout_s=5)

        assert result is None
        assert not should_retry
        assert reason == DroppedEscalationReason.HTTP_400_BAD_REQUEST

    def test_429_exception(self, test_escalation_info: EscalationInfo, mock_gl: Mock):
        """HTTP 429 exceptions should trigger a retry."""
        mock_gl.submit_image_query.side_effect = HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        result, should_retry, _, _ = _escalate_once(test_escalation_info, submit_iq_request_timeout_s=5)

        assert result is None
        assert should_retry

    def test_non_429_http_exception(self, test_escalation_info: EscalationInfo, mock_gl: Mock):
        """Other non-429 HTTP exceptions should not trigger a retry.."""
        mock_gl.submit_image_query.side_effect = HTTPException(status_code=status.HTTP_418_IM_A_TEAPOT)
        result, should_retry, reason, _ = _escalate_once(test_escalation_info, submit_iq_request_timeout_s=5)

        assert result is None
        assert not should_retry
        assert reason == DroppedEscalationReason.HTTP_ERROR

    def test_gl_client_creation_failure(self, test_escalation_info: EscalationInfo):
        """If the Groundlight client cannot be created, _escalate_once should suggest a retry."""
        with patch("app.escalation_queue.manage_reader._groundlight_client") as mock_gl:
            mock_gl.side_effect = GroundlightClientError()
            result, should_retry, _, _ = _escalate_once(test_escalation_info, submit_iq_request_timeout_s=5)

        assert result is None
        assert should_retry


class TestConsumeQueuedEscalation:
    def test_returns_result_on_success(self, test_request_cache: RequestCache, test_escalation_info: EscalationInfo):
        """When _escalate_once succeeds on the first try, should return the ImageQuery and not retry."""
        escalation_str = convert_escalation_info_to_str(test_escalation_info)
        dummy_result = Mock()

        # The request ID for the escalation should not be in the request cache
        assert not test_request_cache.contains(test_escalation_info.request_id)

        with (
            patch(
                "app.escalation_queue.manage_reader._escalate_once", return_value=(dummy_result, False, None, None)
            ) as mock_escalate,
            patch.object(test_request_cache, "contains", wraps=test_request_cache.contains) as mock_contains,
        ):
            result = consume_queued_escalation(escalation_str, test_request_cache, delete_image=False)

        assert result is dummy_result
        mock_escalate.assert_called_once()

        # The request ID should now be in the request cache
        assert test_request_cache.contains(test_escalation_info.request_id)
        # The request ID should have been checked against the request cache
        mock_contains.assert_called_once_with(test_escalation_info.request_id)

    def test_uses_retry_logic_properly(self, test_request_cache: RequestCache, test_escalation_info: EscalationInfo):
        """When escalation fails, we should retry until _escalate_once indicates that we should stop."""
        escalation_str = convert_escalation_info_to_str(test_escalation_info)

        num_retries = 3
        side_effects = [(None, True, None, None)] * num_retries + [
            (None, False, DroppedEscalationReason.HTTP_ERROR, "")
        ]

        with (
            patch("app.escalation_queue.manage_reader._escalate_once", side_effect=side_effects) as mock_escalate,
            patch("app.escalation_queue.manage_reader.time.sleep") as mock_sleep,  # Avoid waiting during the test
        ):
            result = consume_queued_escalation(escalation_str, test_request_cache, delete_image=False)

        assert result is None
        assert mock_escalate.call_count == len(side_effects)

        # All retries should use a shorter request time than the first attempt
        call_times = [call_args[0][1] for call_args in mock_escalate.call_args_list]
        first_request_time = call_times[0]
        assert all(t < first_request_time for t in call_times[1:])

        # Check that time.sleep was called with the expected wait time for each retry
        expected_waits = RETRY_WAIT_TIMES[:num_retries]
        actual_waits = [call_args[0][0] for call_args in mock_sleep.call_args_list]
        assert actual_waits == expected_waits

        # The escalation should be in the request cache
        assert test_request_cache.contains(test_escalation_info.request_id)

    def test_deletes_image_on_completion(self, test_request_cache: RequestCache, test_escalation_info: EscalationInfo):
        """The image for the escalation should be deleted if delete_image is not set to False."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_image_path = Path(temp_dir) / "temp_image.jpeg"
            shutil.copy(test_escalation_info.image_path_str, temp_image_path)

            test_escalation_info.image_path_str = str(temp_image_path)

            escalation_str = convert_escalation_info_to_str(test_escalation_info)
            dummy_result = Mock()

            with patch(
                "app.escalation_queue.manage_reader._escalate_once", return_value=(dummy_result, False, None, None)
            ) as mock_escalate:
                result = consume_queued_escalation(escalation_str, test_request_cache)

            assert result is dummy_result
            mock_escalate.assert_called_once()

            # The image should be deleted after the escalation is finished being consumed
            assert not temp_image_path.exists()

    def test_skips_duplicate_request(self, test_request_id, test_request_cache: RequestCache):
        """When the request ID of an escalation is already in the cache, we should skip the escalation."""
        # Create two escalation infos with a shared request ID, indicating they stem from the same request
        escalation_info_1 = generate_test_escalation_info(request_id=test_request_id)
        escalation_info_2 = generate_test_escalation_info(request_id=test_request_id)

        escalation_str_1 = convert_escalation_info_to_str(escalation_info_1)
        escalation_str_2 = convert_escalation_info_to_str(escalation_info_2)

        with patch(
            "app.escalation_queue.manage_reader._escalate_once", return_value=(None, False, None, None)
        ) as mock_escalate_1:
            consume_queued_escalation(escalation_str_1, test_request_cache, delete_image=False)

        mock_escalate_1.assert_called_once()

        # The request ID should now be in the request cache
        assert test_request_cache.contains(escalation_info_1.request_id)

        with patch("app.escalation_queue.manage_reader._escalate_once") as mock_escalate_2:
            consume_queued_escalation(escalation_str_2, test_request_cache, delete_image=False)

        # Should not have attempted to escalate the second escalation because it has a duplicate request ID
        mock_escalate_2.assert_not_called()

        # The request ID should still be in the request cache
        assert test_request_cache.contains(escalation_info_1.request_id)

    def test_skips_empty_string(self, test_request_cache: RequestCache):
        """Empty string should return None without attempting escalation or updating cache."""
        with patch("app.escalation_queue.manage_reader._escalate_once") as mock_escalate:
            result = consume_queued_escalation("", test_request_cache, delete_image=False)

        assert result is None
        mock_escalate.assert_not_called()
        # Request cache should not have been updated (nothing to cache)
        assert len(list(test_request_cache.cache_dir.iterdir())) == 0

    def test_skips_whitespace_only(self, test_request_cache: RequestCache):
        """Whitespace-only string should return None without attempting escalation or updating cache."""
        with patch("app.escalation_queue.manage_reader._escalate_once") as mock_escalate:
            result = consume_queued_escalation("   \n\t  ", test_request_cache, delete_image=False)

        assert result is None
        mock_escalate.assert_not_called()
        assert len(list(test_request_cache.cache_dir.iterdir())) == 0

    def test_skips_null_bytes(self, test_request_cache: RequestCache):
        """String with null bytes (corruption) should return None without attempting escalation."""
        corrupted_str = "\x00\x00\x00\x00"
        with patch("app.escalation_queue.manage_reader._escalate_once") as mock_escalate:
            result = consume_queued_escalation(corrupted_str, test_request_cache, delete_image=False)

        assert result is None
        mock_escalate.assert_not_called()
        assert len(list(test_request_cache.cache_dir.iterdir())) == 0

    def test_skips_invalid_json(self, test_request_cache: RequestCache):
        """Invalid JSON should return None without attempting escalation."""
        invalid_json = "this is not valid json {"
        with patch("app.escalation_queue.manage_reader._escalate_once") as mock_escalate:
            result = consume_queued_escalation(invalid_json, test_request_cache, delete_image=False)

        assert result is None
        mock_escalate.assert_not_called()
        assert len(list(test_request_cache.cache_dir.iterdir())) == 0

    def test_skips_malformed_escalation_info(self, test_request_cache: RequestCache):
        """Valid JSON but wrong schema should return None without attempting escalation."""
        # Valid JSON but missing required EscalationInfo fields
        malformed_json = json.dumps({"some_key": "some_value"})
        with patch("app.escalation_queue.manage_reader._escalate_once") as mock_escalate:
            result = consume_queued_escalation(malformed_json, test_request_cache, delete_image=False)

        assert result is None
        mock_escalate.assert_not_called()
        assert len(list(test_request_cache.cache_dir.iterdir())) == 0


class TestReadFromEscalationQueue:
    def test_consume_from_reader(self, test_reader: QueueReader, escalation_str: str):
        """Verifies that read_from_escalation_queue consumes from the reader correctly."""
        num_escalations = 3
        escalation_strs = [escalation_str] * num_escalations

        mock_request_cache = Mock()

        # Patch the reader object to iterate over items and then stop
        with (
            patch(
                "app.escalation_queue.manage_reader.consume_queued_escalation",
            ) as mock_consume_escalation,
            patch.object(QueueReader, "__iter__", return_value=iter(escalation_strs)),
        ):
            mock_consume_escalation.return_value = None
            read_from_escalation_queue(test_reader, mock_request_cache)

        assert mock_consume_escalation.call_count == num_escalations
        mock_consume_escalation.assert_has_calls(
            [call(escalation, mock_request_cache) for escalation in escalation_strs],
            any_order=False,
        )

    def test_continues_after_corrupted_line(self, test_reader: QueueReader, test_request_cache: RequestCache):
        """Verifies that read_from_escalation_queue continues processing after a corrupted line."""
        corrupted_line = "\x00\x00corrupted\x00\x00"

        # Use temp copies of the test image since consume_queued_escalation deletes images after processing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_image_1 = Path(temp_dir) / "image1.jpeg"
            temp_image_2 = Path(temp_dir) / "image2.jpeg"
            shutil.copy("test/assets/cat.jpeg", temp_image_1)
            shutil.copy("test/assets/cat.jpeg", temp_image_2)

            # Create two valid escalation strings with different request_ids to avoid deduplication
            escalation_str_1 = convert_escalation_info_to_str(
                generate_test_escalation_info(request_id=generate_request_id(), image_path=str(temp_image_1))
            )
            escalation_str_2 = convert_escalation_info_to_str(
                generate_test_escalation_info(request_id=generate_request_id(), image_path=str(temp_image_2))
            )
            # Sequence: valid, corrupted, valid - should process both valid lines
            escalation_strs = [escalation_str_1, corrupted_line, escalation_str_2]

            dummy_iq = Mock(id="test-iq-id")

            with (
                patch.object(QueueReader, "__iter__", return_value=iter(escalation_strs)),
                patch(
                    "app.escalation_queue.manage_reader._escalate_once",
                    return_value=(dummy_iq, False, None, None),
                ) as mock_escalate,
            ):
                read_from_escalation_queue(test_reader, test_request_cache)

            # Should have called _escalate_once twice (for the two valid lines)
            # The corrupted line should be skipped without calling _escalate_once
            assert mock_escalate.call_count == 2


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
        """Verifies that write_escalation_to_queue properly writes all information to the queue."""
        write_escalation_to_queue(
            test_writer,
            test_escalation_info.detector_id,
            test_image_bytes,
            test_submit_iq_params,
            test_escalation_info.request_id,
        )

        next_escalation_info = EscalationInfo(**json.loads(next(iter(test_reader))))
        assert next_escalation_info.detector_id == test_escalation_info.detector_id
        assert next_escalation_info.submit_iq_params == test_submit_iq_params
        assert Path(next_escalation_info.image_path_str).read_bytes() == test_image_bytes

    def test_write_escalation_to_queue_catches_exception(
        self,
        test_writer: QueueWriter,
        test_escalation_info: EscalationInfo,
        test_image_bytes: bytes,
        test_submit_iq_params: SubmitImageQueryParams,
    ):
        """Verifies that write_escalation_to_queue catches raised exceptions."""
        with (
            patch.object(test_writer, "write_image_bytes", Mock(side_effect=Exception())),
            patch("app.escalation_queue.queue_utils.logger") as mock_logger,
        ):
            write_escalation_to_queue(
                test_writer,
                test_escalation_info.detector_id,
                test_image_bytes,
                test_submit_iq_params,
                test_escalation_info.request_id,
            )
            assert mock_logger.error.called

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
            request_id=test_escalation_info.request_id,
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
                    request_id=test_escalation_info.request_id,
                )

            mock_write_escalation_to_queue.assert_called_once_with(
                writer=test_writer,
                detector_id=test_escalation_info.detector_id,
                image_bytes=test_image_bytes,
                submit_iq_params=test_escalation_info.submit_iq_params,
                request_id=test_escalation_info.request_id,
            )
