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

        # This matches a timestamp in %Y%m%d_%H%M%S_%f format followed by a 27-character KSUID
        self.writing_file_regex = r"\d{8}_\d{6}_\d{6}-.{27}\.txt"
        # This matches the same as the above, with the addition of the tracking file name prefix
        self.tracking_file_regex = rf"{re.escape(TRACKING_FILE_NAME_PREFIX)}{self.writing_file_regex}"

    def __iter__(self) -> Generator[str, None, None]:
        """
        A generator for reading lines written to the escalation queue.

        Blocks until there is a file to read from. Then, each iteration will return the next line from that file until
        all lines have been read, at which point the file being read from will be deleted.

        Tracks the number of lines that have been read from the current file to support recovering from a failure or
        reboot.
        """
        for data_path, tracker_path in self._get_files():
            with data_path.open(mode="r") as escalations, tracker_path.open(mode="a") as tracker:
                lines_to_skip = len(tracker_path.read_text()) if tracker_path.exists() else 0
                for line in islice(escalations, lines_to_skip, None):
                    yield line
                    # NOTE that we write to the tracking file after we yield a line, meaning the below code won't be
                    # executed until the next time the generator is called. This means that at any time, the tracking
                    # file will have one less entry than has been read/returned from the reader. This is by design
                    # because something might go wrong after the reader returns a line, causing it to not get escalated.
                    # We don't want to lose that escalation, so we implement it this way. We allow the possibility of
                    # reading the same line twice (and handle that case in the consumption code) while guaranteeing that
                    # we don't miss any.
                    tracker.write("1")  # Indicates the line that we just yielded has been consumed
                    tracker.flush()  # Write the tracking changes immediately
            # Delete files when done reading
            data_path.unlink()
            tracker_path.unlink()

    def _get_files(self) -> Generator[tuple[Path, Path], None, None]:
        """
        A generator that yields files containing items in the escalation queue.

        Blocks until there is a file to return. Then, returns a tuple:
        - The first item is a Path to the chosen next file to read from
        - The second item is a Path to the associated tracking file
        """
        while True:
            new_reading_path = self._choose_new_file()
            if new_reading_path is not None:
                new_tracking_path = new_reading_path.with_name(f"{TRACKING_FILE_NAME_PREFIX}{new_reading_path.name}")
                yield new_reading_path, new_tracking_path
            else:
                self._sleep(0.1)

    def _choose_new_file(self) -> None | Path:
        """
        Attempts to choose a new file to read from.

        Returns the path to the chosen next file to read from, or None if there are no
        files available. If there are multiple files present, the next chosen file will be the
        oldest one as determined by filename.
        """
        # First we look for tracking files, which will exist if the reader was interrupted while in the middle of
        # processing a file. We finish processing the in-progress files before selecting newly written files.
        tracking_files = [
            path for path in self.base_reading_dir.iterdir() if re.fullmatch(self.tracking_file_regex, path.name)
        ]
        if len(tracking_files) > 0:
            tracking_path = tracking_files[0]
            new_reading_path = Path(tracking_path.parent, tracking_path.name.replace(TRACKING_FILE_NAME_PREFIX, ""))
            return new_reading_path

        # If there were no tracking files, we look for fresh files to process and select the oldest one.
        queue_files = [
            path for path in self.base_writing_dir.iterdir() if re.fullmatch(self.writing_file_regex, path.name)
        ]
        if len(queue_files) == 0:
            return None

        oldest_writing_path = sorted(queue_files)[0]
        new_reading_path = self.base_reading_dir / oldest_writing_path.name

        # Move the file from writing directory to reading directory
        oldest_writing_path.rename(new_reading_path)

        return new_reading_path

    def _sleep(self, duration: float) -> None:
        """
        Sleeps for the specified duration.

        This method is defined like this to avoid patching `time.sleep` directly in testing.
        """
        time.sleep(duration)
