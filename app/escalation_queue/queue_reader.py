import logging
import os
import re
import time
from itertools import islice
from pathlib import Path
from typing import Generator

from app.escalation_queue.constants import (
    DEFAULT_QUEUE_BASE_DIR,
    READING_DIR_SUFFIX,
    TRACKING_FILE_NAME_PREFIX,
    WRITING_DIR_SUFFIX,
)

logger = logging.getLogger(__name__)


class QueueReader:
    """Manages reading escalation data from a file-based queue system."""

    def __init__(self, base_dir: str = DEFAULT_QUEUE_BASE_DIR):
        self.base_reading_dir = Path(base_dir, READING_DIR_SUFFIX)
        os.makedirs(self.base_reading_dir, exist_ok=True)  # Ensure base_reading_dir exists
        self.base_writing_dir = Path(base_dir, WRITING_DIR_SUFFIX)
        os.makedirs(self.base_writing_dir, exist_ok=True)  # Ensure base_writing_dir exists

        self.current_reading_file_path: Path | None = None
        self.current_tracking_file_path: Path | None = None
        self.continuing_from_tracking_file = False

        # This matches a timestamp in %Y%m%d_%H%M%S_%f format followed by a 27-character KSUID
        self.writing_file_regex = r"\d{8}_\d{6}_\d{6}-.{27}\.txt"
        # This matches the same as the above, with the addition of the tracking file name prefix
        self.tracking_file_regex = rf"{re.escape(TRACKING_FILE_NAME_PREFIX)}{self.writing_file_regex}"

        self._line_generator = self._get_line_generator()

    def __iter__(self):
        return self._blocking_line_generator()

    def _blocking_line_generator(self) -> Generator[str, None, None]:
        """Generator that yields lines from the queue, blocking until a line is available."""
        while True:
            line = self._get_next_line()
            if line is not None:
                yield line
            else:
                time.sleep(0.1)

    def _get_next_line(self) -> str | None:
        """Returns the next line to be read, or None if there are no lines to read."""
        try:
            return next(self._line_generator)
        except StopIteration:
            self._line_generator = (
                self._get_line_generator()
            )  # Recreate the generator so that it can look for a file again
            return None

    def _get_num_tracked_escalations(self) -> int:
        """
        Returns the number of escalations recorded in the current tracking file. Returns 0 if there is no such file.
        """
        if self.current_tracking_file_path is None:
            return 0
        with self.current_tracking_file_path.open(mode="r") as f:
            return len(f.readline())

    def _get_line_generator(self) -> Generator[str, None, None]:
        """
        A generator for reading lines written to the escalation queue.

        If there is no file currently being read from, a new file will be chosen and moved to the reading directory.
        Then, each iteration will return the next line from that file until all lines have been read, at which point the
        file being read from will be deleted.

        Tracks the number of lines that have been read from the current file to support recovering from a failure or
        reboot.

        If there aren't any files to read, raises StopIteration.
        """
        while True:
            if not self.current_reading_file_path or not self.current_reading_file_path.exists():
                new_file_path, continuing_from_tracking_file = self._choose_new_file()
                if new_file_path is None:
                    return  # Triggers a StopIteration exception
                self.current_reading_file_path = new_file_path
                self.current_tracking_file_path = self.current_reading_file_path.with_name(
                    f"{TRACKING_FILE_NAME_PREFIX}{self.current_reading_file_path.name}"
                )
                self.continuing_from_tracking_file = continuing_from_tracking_file

            with (
                self.current_reading_file_path.open(mode="r") as reading_fd,
                self.current_tracking_file_path.open(mode="a") as tracking_fd,
            ):
                line_to_start_reading_from = 0
                if self.continuing_from_tracking_file:
                    num_previous_escalations = self._get_num_tracked_escalations()
                    line_to_start_reading_from = num_previous_escalations

                for line in islice(reading_fd, line_to_start_reading_from, None):
                    yield line
                    # NOTE that we write to the tracking file after we yield a line, meaning the below code won't be
                    # executed until the next time the generator is called. This means that at any time, the tracking
                    # file will have one less entry than has been read/returned from the reader. This is by design
                    # because something might go wrong after the reader returns a line, causing it to not get escalated.
                    # We don't want to lose that escalation, so we implement it this way. We allow the possibility of
                    # reading the same line twice (and handle that case in the consumption code) while guaranteeing that
                    # we don't miss any.
                    tracking_fd.write("1")  # Indicates the line that we just yielded has been consumed
                    tracking_fd.flush()  # Write the tracking changes immediately
                self.current_reading_file_path.unlink()  # Delete file when done reading
                self.current_tracking_file_path.unlink()
                self.current_reading_file_path = None
                self.current_tracking_file_path = None

    def _choose_new_file(self) -> tuple[None | Path, bool]:
        """
        Attempts to choose a new file to read from.

        Returns a tuple:
        - The first item is a path to the chosen next file to read from, or None if there are no
          files in the base writing directory. If there are multiple files present, the next chosen file will be the
          oldest one as determined by filename.
        - The second item is a bool which is True if the file was chosen from an unfinished tracking file, and False
          otherwise.
        """
        # First we look for tracking files, which will exist if the reader was interrupted while in the middle of
        # processing a file. We finish processing the in-progress files before selecting newly written files.
        tracking_files = [
            path for path in self.base_reading_dir.iterdir() if re.fullmatch(self.tracking_file_regex, path.name)
        ]
        if len(tracking_files) > 0:
            tracking_path = tracking_files[0]
            new_reading_path = Path(tracking_path.parent, tracking_path.name.replace(TRACKING_FILE_NAME_PREFIX, ""))
            return new_reading_path, True

        # If there were no tracking files, we look for fresh files to process and select the oldest one.
        queue_files = [
            path for path in self.base_writing_dir.iterdir() if re.fullmatch(self.writing_file_regex, path.name)
        ]
        if len(queue_files) == 0:
            return None, False

        oldest_writing_path = sorted(queue_files)[0]
        new_reading_path = (
            oldest_writing_path.replace(  # This will overwrite if the target path exists (which shouldn't happen)
                oldest_writing_path.parent.parent / READING_DIR_SUFFIX / oldest_writing_path.name
            )
        )
        return new_reading_path, False
