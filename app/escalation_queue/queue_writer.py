import json
import logging
import os
from datetime import datetime
from pathlib import Path

import ksuid
from pydantic import BaseModel

DEFAULT_QUEUE_BASE_DIR = "/opt/groundlight/queue"

logger = logging.getLogger(__name__)


class EscalationInfo(BaseModel):
    detector_id: str
    image_path: str


class QueueWriter:
    def __init__(self, base_dir: str = DEFAULT_QUEUE_BASE_DIR):
        self.base_writing_dir = Path(base_dir, "writing")
        os.makedirs(self.base_writing_dir, exist_ok=True)  # Ensure base_writing_dir exists
        self.last_file_path: Path | None = None

    def write_escalation(self, escalation_info: EscalationInfo) -> bool:
        if not self.last_file_path or not self.last_file_path.exists():
            logger.debug("last_file_path does not exist, generating new one")
            new_path = self._generate_new_path()
            self.last_file_path = new_path

        wrote_successfully = self._write_to_path(self.last_file_path, escalation_info)
        return wrote_successfully

    def _write_to_path(self, path_to_write_to: Path, data: EscalationInfo) -> bool:
        try:
            with open(path_to_write_to, "a") as f:
                f.write(f"{json.dumps(data.model_dump())}\n")
            return True
        except OSError as e:
            logger.error(f"Failed to write to {path_to_write_to} with error {e}.")
            return False  # TODO should this retry?

    def _generate_new_path(self) -> Path:
        format = "%Y%m%d_%H%M%S_%f"  # Highest time precision available
        new_file_name = f"{datetime.now().strftime(format)}-{ksuid.KsuidMs()}.txt"
        new_file_path = Path.joinpath(self.base_writing_dir, new_file_name)
        return new_file_path
