import logging
import os
from pathlib import Path
from typing import Generator

from app.escalation_queue.queue_writer import DEFAULT_QUEUE_BASE_DIR

logger = logging.getLogger(__name__)


class QueueReader:
    def __init__(self, base_dir: str = DEFAULT_QUEUE_BASE_DIR):
        self.base_reading_dir = Path(base_dir, "reading")
        os.makedirs(self.base_reading_dir, exist_ok=True)  # Ensure base_reading_dir exists
        self.base_writing_dir = Path(base_dir, "writing")  # It's okay if this doesn't exist (yet)
        self.current_file_path: Path | None = None

        self._generator = self._get_line_generator()

    def get_next_line(self) -> str | None:
        """Returns the next line to be read, or None if there are no lines to read."""
        try:
            return next(self._generator)
        except StopIteration:
            self._generator = self._get_line_generator()  # Recreate the generator so that it can look for a file again
            return None

    def _get_line_generator(self) -> Generator[str, None, None]:
        """
        Generator for producing lines to be read.
        The generator chooses a file, moves it to reading directory, reads all lines, repeats.
        If there aren't any files to read, raises StopIteration.
        """
        while True:
            if not self.current_file_path or not self.current_file_path.exists():
                new_file_path = self._choose_new_file()
                if new_file_path is None:
                    return  # Triggers a StopIteration exception
                self.current_file_path = new_file_path

            logger.info(f"{self.current_file_path=}")
            with open(self.current_file_path, "r") as f:
                for line in f:
                    logger.info(f"{line=}")
                    yield line
                self.current_file_path.unlink()  # Delete file when done reading
                self.current_file_path = None

    def _choose_new_file(self) -> None | Path:
        """Returns None if no files are in the base_dir, otherwise the least element."""
        queue_files = list(self.base_writing_dir.glob("*_*-*.txt"))  # TODO improve this?
        if len(queue_files) == 0:
            return None

        oldest_writing_path = Path(sorted(queue_files)[0])
        logger.info(f"{oldest_writing_path=}")
        new_reading_path = (
            oldest_writing_path.replace(  # This will overwrite if the target path exists (which shouldn't happen)
                oldest_writing_path.parent.parent / "reading" / oldest_writing_path.name
            )
        )
        logger.info(f"{new_reading_path=}")
        return new_reading_path
