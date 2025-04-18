import logging
import os
from pathlib import Path
from typing import Generator

from app.escalation_queue.constants import DEFAULT_QUEUE_BASE_DIR

logger = logging.getLogger(__name__)


class QueueReader:
    def __init__(self, base_dir: str = DEFAULT_QUEUE_BASE_DIR):
        self.base_reading_dir = Path(base_dir, "reading")
        os.makedirs(self.base_reading_dir, exist_ok=True)  # Ensure base_reading_dir exists
        self.base_writing_dir = Path(base_dir, "writing")  # It's okay if this doesn't exist (yet)
        self.current_file_path: Path | None = None
        self.current_tracking_file_path: Path | None = None

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
                new_file_path = (
                    self._choose_new_file()
                )  # TODO need to know if this is an existing file (from tracked file) and treat it different
                if new_file_path is None:
                    return  # Triggers a StopIteration exception
                self.current_file_path = new_file_path
                self.current_tracking_file_path = self.current_file_path.with_name(
                    f"tracking-{self.current_file_path.name}"
                )

            with (
                self.current_file_path.open(mode="r") as reading_fd,
                self.current_tracking_file_path.open(mode="a") as tracking_fd,
            ):
                for line in reading_fd:
                    tracking_fd.write("1")
                    tracking_fd.flush()
                    yield line
                self.current_file_path.unlink()  # Delete file when done reading
                self.current_tracking_file_path.unlink()  # Delete tracking file when done reading
                self.current_file_path = None
                self.current_tracking_file_path = None

    def _choose_new_file(self) -> None | Path:
        """Returns None if no files are in the base_dir, otherwise the least element."""
        # tracking_files = list(self.base_reading_dir.glob("tracking-*_*-*.txt"))
        # if len(tracking_files) > 0:
        #     logger.info("Found at least one unfinished tracking file. Choosing a random one and continuing from there.")
        #     tracking_path = tracking_files[0]
        #     new_reading_path = Path(tracking_path.parent, tracking_path.name.replace("tracking-", ""))
        #     return new_reading_path

        queue_files = list(self.base_writing_dir.glob("*_*-*.txt"))  # TODO improve this?
        if len(queue_files) == 0:
            return None

        oldest_writing_path = Path(sorted(queue_files)[0])
        new_reading_path = (
            oldest_writing_path.replace(  # This will overwrite if the target path exists (which shouldn't happen)
                oldest_writing_path.parent.parent / "reading" / oldest_writing_path.name
            )
        )
        return new_reading_path
