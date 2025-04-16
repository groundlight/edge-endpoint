import json
import logging
import os
from pathlib import Path
from typing import Any

import ksuid
from pydantic import BaseModel

from app.core.utils import get_formatted_timestamp_str
from app.escalation_queue.constants import DEFAULT_QUEUE_BASE_DIR, MAX_QUEUE_FILE_LINES

logger = logging.getLogger(__name__)


class SubmitImageQueryParams(BaseModel):
    wait: float | None
    patience_time: float | None
    confidence_threshold: float
    human_review: str | None
    want_async: bool
    metadata: dict[str, Any] | None
    image_query_id: str | None


class EscalationInfo(BaseModel):
    timestamp: str
    detector_id: str
    image_path: str
    submit_iq_params: SubmitImageQueryParams


class QueueWriter:
    def __init__(self, base_dir: str = DEFAULT_QUEUE_BASE_DIR):
        self.base_writing_dir = Path(base_dir, "writing")
        os.makedirs(self.base_writing_dir, exist_ok=True)  # Ensure base_writing_dir exists
        self.base_image_dir = Path(base_dir, "images")
        os.makedirs(self.base_image_dir, exist_ok=True)  # Ensure base_image_dir exists

        self.last_file_path: Path | None = None
        self.num_lines_written_to_file: int = 0

    def write_image_bytes(self, image_bytes: bytes, detector_id: str, timestamp: str) -> str:
        """
        Writes the image bytes to a unique path based on the detector ID and timestamp and returns the path.
        """
        image_file_name = f"{detector_id}-{timestamp}-{ksuid.KsuidMs()}"
        image_path = Path.joinpath(self.base_image_dir, image_file_name)
        image_path.write_bytes(image_bytes)

        return str(image_path.resolve())

    def write_escalation(self, escalation_info: EscalationInfo) -> bool:
        # TODO docstring
        if (
            not self.last_file_path
            or not self.last_file_path.exists()
            or self.num_lines_written_to_file >= MAX_QUEUE_FILE_LINES
        ):
            logger.debug("last_file_path does not exist or has reached maximum length, generating new one")
            new_path = self._generate_new_path()
            self.last_file_path = new_path
            self.num_lines_written_to_file = 0

        wrote_successfully = self._write_to_path(self.last_file_path, escalation_info)
        if wrote_successfully:
            self.num_lines_written_to_file += 1
        return wrote_successfully

    def _write_to_path(self, path_to_write_to: Path, data: EscalationInfo) -> bool:
        try:
            with open(path_to_write_to, "a") as f:  # TODO open once per file, instead of once per write?
                f.write(f"{json.dumps(data.model_dump())}\n")
            return True
        except OSError as e:
            logger.error(f"Failed to write to {path_to_write_to} with error {e}.")
            return False  # TODO should this retry?

    def _generate_new_path(self) -> Path:
        new_file_name = f"{get_formatted_timestamp_str()}-{ksuid.KsuidMs()}.txt"
        new_file_path = Path.joinpath(self.base_writing_dir, new_file_name)
        return new_file_path
