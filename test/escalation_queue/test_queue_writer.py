import os
import shutil

import pytest

from app.escalation_queue.queue_writer import EscalationInfo, QueueWriter


@pytest.fixture
def test_escalation():
    data = {"detector_id": "test_id", "image_path": "test_path"}
    return EscalationInfo(**data)


@pytest.fixture
def base_dir():  # TODO check if this is needed
    return "/home/corey/ptdev/edge-endpoint/test-queue"


@pytest.fixture
def writer(base_dir):
    if os.path.isdir(base_dir):  # TODO remove and use temp directory
        shutil.rmtree(base_dir)

    return QueueWriter(base_dir=base_dir)


def assert_file_length(file_path: str, expected_lines: int):
    with open(file_path, "r") as f:
        num_lines = len(f.readlines())
        assert num_lines == expected_lines


def test_writes_go_to_same_file(writer: QueueWriter, test_escalation: EscalationInfo):
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

    os.remove(first_file_path)
    assert writer.write_escalation(test_escalation)
    assert_file_length(writer.last_file_path, 1)
    assert first_file_path != writer.last_file_path
