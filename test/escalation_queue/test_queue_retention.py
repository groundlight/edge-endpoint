import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.escalation_queue import queue_retention
from app.escalation_queue.queue_retention import QUEUE_RETENTION_DAYS, prune_expired_queue_data

# Ages expressed relative to the configured window so the tests hold if the retention period changes.
_OLDER_THAN_WINDOW = QUEUE_RETENTION_DAYS + 1
_WITHIN_WINDOW = max(QUEUE_RETENTION_DAYS - 1, 0)

# The (images, writing, reading, failed) directories yielded by the `dirs` fixture.
RetentionDirs = tuple[Path, Path, Path, Path]


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RetentionDirs:
    """Redirect every retention directory to temp subdirectories."""
    images = tmp_path / "images"
    writing = tmp_path / "writing"
    reading = tmp_path / "reading"
    failed = tmp_path / "failed"
    retention_dirs = (images, writing, reading, failed)
    for d in retention_dirs:
        d.mkdir()
    monkeypatch.setattr(queue_retention, "RETENTION_DIRS", retention_dirs)
    return retention_dirs


def _write(path: Path, age_days: float) -> Path:
    path.write_text("data")
    ts = (datetime.now(timezone.utc) - timedelta(days=age_days)).timestamp()
    os.utime(path, (ts, ts))
    return path


def test_deletes_data_older_than_window_in_every_dir(dirs: RetentionDirs):
    """Files past the retention window are deleted across images, writing, reading, and failed dirs."""
    images, writing, reading, failed = dirs
    old = [
        _write(images / "img", age_days=_OLDER_THAN_WINDOW),
        _write(writing / "queue.txt", age_days=_OLDER_THAN_WINDOW),
        _write(reading / "queue.txt", age_days=_OLDER_THAN_WINDOW),
        _write(failed / "record.json", age_days=_OLDER_THAN_WINDOW),
    ]
    prune_expired_queue_data()
    for p in old:
        assert not p.exists()


def test_keeps_data_within_window(dirs: RetentionDirs):
    """Files newer than the retention window are kept, regardless of directory."""
    images, writing, reading, failed = dirs
    recent = [
        _write(images / "img", age_days=_WITHIN_WINDOW),
        _write(writing / "queue.txt", age_days=_WITHIN_WINDOW),
        _write(reading / "queue.txt", age_days=0),
        _write(failed / "record.json", age_days=_WITHIN_WINDOW),
    ]
    prune_expired_queue_data()
    for p in recent:
        assert p.exists()


def test_deletes_pending_escalation_regardless_of_status(dirs: RetentionDirs):
    """Old pending escalation data + its image are removed even though they were never escalated."""
    images, writing, _, _ = dirs
    img = _write(images / "det-x-999", age_days=_OLDER_THAN_WINDOW)
    queue_line = _write(writing / "20200101_000000_000000-abc.txt", age_days=_OLDER_THAN_WINDOW)
    prune_expired_queue_data()
    assert not img.exists()
    assert not queue_line.exists()


def test_ignores_subdirectories(dirs: RetentionDirs):
    """Non-file entries are skipped without error."""
    images, *_ = dirs
    (images / "nested").mkdir()
    _write(images / "img", age_days=_OLDER_THAN_WINDOW)
    prune_expired_queue_data()  # Should not raise
    assert (images / "nested").exists()


def test_missing_dir_is_skipped(dirs: RetentionDirs, monkeypatch: pytest.MonkeyPatch):
    """A retention dir that does not exist is skipped rather than raising."""
    images, writing, reading, failed = dirs
    monkeypatch.setattr(queue_retention, "RETENTION_DIRS", (Path("/nonexistent/queue/images"), images))
    _write(images / "img", age_days=_OLDER_THAN_WINDOW)
    prune_expired_queue_data()  # Should not raise
    assert not (images / "img").exists()
