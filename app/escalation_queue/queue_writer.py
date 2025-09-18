import json
import os
from pathlib import Path

import ksuid

from app.core.utils import get_formatted_timestamp_str
from app.escalation_queue.constants import (
    DEFAULT_QUEUE_BASE_DIR,
    IMAGE_DIR_SUFFIX,
    MAX_QUEUE_FILE_LINES,
    WRITING_DIR_SUFFIX,
)
from app.escalation_queue.models import EscalationInfo
from app.utils.loghelper import create_logger

logger = create_logger(__name__, component="escalation-queue-reader")


def convert_escalation_info_to_str(escalation_info: EscalationInfo) -> str:
    """Converts an `EscalationInfo` object to string form, which can be written to and read from a file."""
    return f"{json.dumps(escalation_info.model_dump())}\n"


class QueueWriter:
    """Handles writing escalation data and associated images to a file-based queue system."""

    def __init__(self, base_dir: str = DEFAULT_QUEUE_BASE_DIR):
        self.base_writing_dir = Path(base_dir, WRITING_DIR_SUFFIX)
        os.makedirs(self.base_writing_dir, exist_ok=True)  # Ensure base_writing_dir exists
        self.base_image_dir = Path(base_dir, IMAGE_DIR_SUFFIX)
        os.makedirs(self.base_image_dir, exist_ok=True)  # Ensure base_image_dir exists

        self.last_file_path: Path | None = None
        self.num_lines_written_to_file: int = 0

    def write_image_bytes(self, image_bytes: bytes, detector_id: str, timestamp: str) -> str:
        """
        Writes the provided image bytes to a unique path based on the detector ID and timestamp and returns the absolute
        path as a string.
        """
        image_file_name = f"{detector_id}-{timestamp}-{ksuid.KsuidMs()}"
        image_path = Path.joinpath(self.base_image_dir, image_file_name)
        image_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory of target path exists.
        image_path.write_bytes(image_bytes)

        return str(image_path.resolve())

    def write_escalation(self, escalation_info: EscalationInfo) -> bool:
        """
        Writes the provided escalation info to the queue.

        Will write to the last used file path if it exists and has not exceeded the maximum length. Otherwise will
        create a new file to write the escalation to.

        Returns True if the write succeeds and False otherwise.
        """
        is_new_file = False
        if self.last_file_path is None or self.num_lines_written_to_file >= MAX_QUEUE_FILE_LINES:
            self._reset_to_new_file()
            is_new_file = True

        wrote_successfully = self._write_to_path(self.last_file_path, escalation_info, is_new_file)
        if wrote_successfully:
            self.num_lines_written_to_file += 1
        return wrote_successfully

    def _write_to_path(self, path_to_write_to: Path, data: EscalationInfo, is_new_file: bool) -> bool:
        """Writes the provided data to the provided path. Returns True if the write succeeds and False otherwise."""
        try:
            path_to_write_to.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory of target path exists.

            flags = os.O_WRONLY | os.O_APPEND
            if is_new_file:
                # If we know the file does not yet exist, we want to create it and open it.
                flags |= os.O_CREAT
                fd = os.open(path_to_write_to, flags)
            else:
                try:
                    # If we think the file exists (because we wrote to it before) but aren't certain (because the reader
                    # could have moved it), we assume it exists and try to open it for appending. If the file doesn't
                    # exist, this will raise a FileNotFoundError.
                    fd = os.open(path_to_write_to, flags)
                except FileNotFoundError:
                    # If the file doesn't exist (e.g., if the reader moved it) we reset to a new path.
                    self._reset_to_new_file()
                    flags |= os.O_CREAT
                    fd = os.open(self.last_file_path, flags)

            # TODO this could be optimized by opening each file only once, instead of on each write.
            with os.fdopen(fd, "a") as f:
                f.write(convert_escalation_info_to_str(data))
            return True
        except OSError as e:
            logger.error(f"Failed to write to {path_to_write_to} with error {e}.")
            return False

    def _generate_new_path(self) -> Path:
        """Generates a new unique path in the writing directory."""
        new_file_name = f"{get_formatted_timestamp_str()}-{ksuid.KsuidMs()}.txt"
        new_file_path = Path.joinpath(self.base_writing_dir, new_file_name)
        return new_file_path

    def _reset_to_new_file(self) -> None:
        """Generates a new path, sets the `last_file_path` to the new path, and resets the line number counter to 0."""
        new_path = self._generate_new_path()
        self.last_file_path = new_path
        self.num_lines_written_to_file = 0
