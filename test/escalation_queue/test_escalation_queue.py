import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator, Iterator
from unittest.mock import patch

import ksuid
import pytest

from app.core.utils import get_formatted_timestamp_str
from app.escalation_queue.constants import MAX_QUEUE_FILE_LINES
from app.escalation_queue.models import EscalationInfo, SubmitImageQueryParams
from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.queue_writer import QueueWriter

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
    def assert_expected_reader_output(
        self, reader_iter: QueueReader | Iterator[str], expected_values: list[EscalationInfo]
    ):
        """
        Helper function to assert that the reader produces an expected list of escalations.

        The `reader_iter` argument can be either a QueueReader or an Iterator. The latter case allows previous iteration
        progress to be preserved between calls.
        """
        for value, escalation_str in zip(expected_values, reader_iter):
            assert EscalationInfo(**json.loads(escalation_str)) == value

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
            self.assert_expected_reader_output(test_reader, [test_escalation_info])
            assert mock_wait.call_count == num_wait_calls  # Verify that the reader waited for the specified # of times

    def test_reader_moves_file(
        self, test_reader: QueueReader, test_writer: QueueWriter, test_escalation_info: EscalationInfo
    ):
        """Verify that the reader moves the file being read."""
        assert test_writer.write_escalation(test_escalation_info)
        written_to_path = test_writer.last_file_path

        self.assert_expected_reader_output(test_reader, [test_escalation_info])
        assert not written_to_path.exists()

    def test_reader_reads_multiple_lines_from_same_file(self, test_reader: QueueReader, test_writer: QueueWriter):
        """
        Verify that the reader can read multiple lines from the same file in the correct order.
        """
        test_escalation_infos = [generate_test_escalation_info(detector_id=f"test_id_{i}") for i in range(3)]

        for escalation_info in test_escalation_infos:
            assert test_writer.write_escalation(escalation_info)

        self.assert_expected_reader_output(test_reader, test_escalation_infos)

    def test_reader_prioritizes_oldest_file(self, test_base_dir: str, test_reader: QueueReader):
        """Verify that the reader reads from the oldest file first."""
        test_escalation_info_1 = generate_test_escalation_info(detector_id="test_id_1")
        test_escalation_info_2 = generate_test_escalation_info(detector_id="test_id_2")

        first_writer = generate_queue_writer(test_base_dir)
        second_writer = generate_queue_writer(test_base_dir)
        assert first_writer.write_escalation(test_escalation_info_1)
        assert second_writer.write_escalation(test_escalation_info_2)

        self.assert_expected_reader_output(test_reader, [test_escalation_info_1, test_escalation_info_2])

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
        self.assert_expected_reader_output(reader_iter, [test_escalation_info_1])
        # Reading directory should contain the first pair of reading and tracking files
        assert len([p for p in reading_dir.iterdir()]) == num_files_in_pair

        self.assert_expected_reader_output(reader_iter, [test_escalation_info_2])
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
        self.assert_expected_reader_output(first_reader, [test_escalation_infos[0], test_escalation_infos[1]])

        # Now a new reader should continue from the 2nd written escalation in the partially-read file,
        # because there's only record of one escalation from that file being finished.
        second_reader = generate_queue_reader(test_base_dir)
        self.assert_expected_reader_output(second_reader, [test_escalation_infos[1], test_escalation_infos[2]])

    def test_reader_resumes_multiple_times_correctly(self, test_base_dir: str, test_writer: QueueWriter):
        """Verify that the reader can resume from a file multiple times, and start from the proper place each time."""
        # Write six unique escalations to a file
        test_escalation_infos = [generate_test_escalation_info(detector_id=f"test_id_{i}") for i in range(6)]
        for escalation_info in test_escalation_infos:
            assert test_writer.write_escalation(escalation_info)

        # Read the first two lines from the file
        first_reader = generate_queue_reader(test_base_dir)
        self.assert_expected_reader_output(first_reader, [test_escalation_infos[0], test_escalation_infos[1]])

        # Now a new reader should continue from the 2nd written escalation in the partially-read file
        second_reader = generate_queue_reader(test_base_dir)
        self.assert_expected_reader_output(second_reader, [test_escalation_infos[1], test_escalation_infos[2]])

        # Now a new reader should continue from the 3rd written escalation in the partially-read file
        third_reader = generate_queue_reader(test_base_dir)
        self.assert_expected_reader_output(third_reader, [test_escalation_infos[2], test_escalation_infos[3]])

    def test_reader_prioritizes_tracking_file(self, test_base_dir: str):
        """Verify that the reader chooses a tracking file over a normal written file when there's one available."""
        # Write three escalations to a file
        test_escalation_info_1 = generate_test_escalation_info(detector_id="test_id_1")
        first_writer = generate_queue_writer(test_base_dir)
        for _ in range(3):
            assert first_writer.write_escalation(test_escalation_info_1)
        # Read two lines from the file
        first_reader = generate_queue_reader(test_base_dir)
        self.assert_expected_reader_output(first_reader, [test_escalation_info_1] * 2)

        # Create a new written file
        test_escalation_info_2 = generate_test_escalation_info(detector_id="test_id_2")
        second_writer = generate_queue_writer(test_base_dir)
        assert second_writer.write_escalation(test_escalation_info_2)

        # Ensure a new reader will read from the in progress file before the newly written file
        second_reader = generate_queue_reader(test_base_dir)
        self.assert_expected_reader_output(second_reader, [test_escalation_info_1] * 2 + [test_escalation_info_2])

    def test_reader_selects_empty_tracking_file(self, test_base_dir: str, test_writer: QueueWriter):
        """Verify that the reader will select a tracking file even if it contains no tracked escalations."""
        test_escalation_info_1 = generate_test_escalation_info(detector_id="test_id_1")
        assert test_writer.write_escalation(test_escalation_info_1)
        first_reader = generate_queue_reader(test_base_dir)
        self.assert_expected_reader_output(first_reader, [test_escalation_info_1])

        # Now there should be an empty tracking file created by the first reader, which the second reader should select
        test_escalation_info_2 = generate_test_escalation_info(detector_id="test_id_2")
        assert test_writer.write_escalation(test_escalation_info_2)
        second_reader = generate_queue_reader(test_base_dir)
        self.assert_expected_reader_output(second_reader, [test_escalation_info_1, test_escalation_info_2])
