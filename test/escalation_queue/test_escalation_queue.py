import json
import os
import shutil
import tempfile
from typing import Generator

import ksuid
import pytest

from app.escalation_queue.queue_reader import QueueReader
from app.escalation_queue.queue_writer import EscalationInfo, QueueWriter

### Helper functions


def generate_test_escalation(detector_id: str = "test_id", image_path: str = "test_path") -> EscalationInfo:
    data = {"detector_id": detector_id, "image_path": image_path}
    return EscalationInfo(**data)


def assert_file_length(file_path: str, expected_lines: int):
    with open(file_path, "r") as f:
        num_lines = len(f.readlines())
        assert num_lines == expected_lines


def assert_contents_of_next_read_line(reader: QueueReader, expected_result: EscalationInfo | None):  # TODO rename
    next_escalation_str = reader.get_next_line()
    next_escalation = None if next_escalation_str is None else EscalationInfo(**json.loads(next_escalation_str))
    assert next_escalation == expected_result


### Fixtures


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
    assert writer.write_escalation(test_escalation)
    assert_file_length(writer.last_file_path, 1)

    assert writer.write_escalation(test_escalation)
    assert_file_length(writer.last_file_path, 2)


def test_write_to_different_file(writer: QueueWriter, test_escalation: EscalationInfo):
    """Verify that the writer uses a new file when the previous one is gone."""
    assert writer.write_escalation(test_escalation)
    first_file_path = writer.last_file_path
    assert_file_length(first_file_path, 1)

    first_file_path.unlink()
    assert writer.write_escalation(test_escalation)
    assert_file_length(writer.last_file_path, 1)
    assert first_file_path != writer.last_file_path


def test_separate_writers_write_to_different_files(
    writer: QueueWriter, second_writer: QueueWriter, test_escalation: EscalationInfo
):
    """Verify that separate writers will write to separate files."""
    assert writer.write_escalation(test_escalation)
    assert second_writer.write_escalation(test_escalation)

    assert writer.last_file_path != second_writer.last_file_path

    assert_file_length(writer.last_file_path, 1)
    assert_file_length(second_writer.last_file_path, 1)


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
    assert writer.last_file_path != second_writer.last_file_path

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
