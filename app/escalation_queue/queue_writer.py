import os
from datetime import datetime
from pathlib import Path

import ksuid
from pydantic import BaseModel


class EscalationInfo(BaseModel):
    detector_id: str
    image_path: str


class QueueWriter:
    def __init__(self, base_dir: str = "/opt/groundlight/edge/escalation_queue"):
        self.base_dir = Path(base_dir)
        # self.base_dir.mkdir(parents=True, exist_ok=True)
        os.makedirs(self.base_dir, exist_ok=True)
        self.last_file_path: Path | None = None

    def write_escalation(self, escalation_info: EscalationInfo) -> bool:
        if not self.last_file_path or not self.last_file_path.exists():
            new_path = self._generate_new_path()
            self.last_file_path = new_path

        wrote_successfully = self._write_to_path(self.last_file_path, escalation_info)

        return wrote_successfully

    def _write_to_path(self, path_to_write_to: Path, data: EscalationInfo) -> bool:
        with open(path_to_write_to, "a") as f:
            f.write(str(data.model_dump()))

    def _generate_new_path(self) -> Path:
        format = "%Y%m%d_%H%M%S"
        new_file_name = f"{datetime.now().strftime(format)}-{ksuid.KsuidMs()}.txt"
        new_file_path = Path.joinpath(self.base_dir, new_file_name)
        return new_file_path
