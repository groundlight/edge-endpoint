import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.escalation_queue import image_retention
from app.escalation_queue.image_retention import prune_orphaned_images


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the image dir and the queue-entry dirs to temp directories."""
    image_dir = tmp_path / "images"
    writing_dir = tmp_path / "writing"
    reading_dir = tmp_path / "reading"
    for d in (image_dir, writing_dir, reading_dir):
        d.mkdir()
    monkeypatch.setattr(image_retention, "IMAGE_DIR", image_dir)
    monkeypatch.setattr(image_retention, "QUEUE_ENTRY_DIRS", (writing_dir, reading_dir))
    return image_dir, writing_dir, reading_dir


def _age(path: Path, days: int) -> None:
    """Backdate a file's mtime by the given number of days."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    os.utime(path, (ts, ts))


def _make_image(image_dir: Path, name: str, age_days: int) -> Path:
    img = image_dir / name
    img.write_bytes(b"fake-image")
    _age(img, age_days)
    return img


def _queue_file(queue_dir: Path, name: str, image_paths: list[Path]) -> Path:
    """Write a queue file whose lines reference the given images (as the writer stores them: resolved paths)."""
    lines = [json.dumps({"image_path_str": str(p.resolve())}) for p in image_paths]
    f = queue_dir / name
    f.write_text("\n".join(lines) + "\n")
    return f


def test_deletes_orphaned_image_past_retention(dirs):
    """An old image not referenced by any queue entry should be deleted."""
    image_dir, _, _ = dirs
    img = _make_image(image_dir, "orphan", age_days=31)
    prune_orphaned_images()
    assert not img.exists()


def test_keeps_recent_orphaned_image(dirs):
    """An unreferenced image within the retention window should be kept (guards the write race)."""
    image_dir, _, _ = dirs
    img = _make_image(image_dir, "recent-orphan", age_days=1)
    prune_orphaned_images()
    assert img.exists()


def test_keeps_referenced_image_even_when_old(dirs):
    """An old image still referenced by a queued escalation must NOT be deleted."""
    image_dir, writing_dir, _ = dirs
    img = _make_image(image_dir, "pending", age_days=45)
    _queue_file(writing_dir, "20200101_000000_000000-abc.txt", [img])
    prune_orphaned_images()
    assert img.exists()


def test_keeps_image_referenced_from_reading_dir(dirs):
    """Images referenced by an in-progress (reading dir) queue file must be kept."""
    image_dir, _, reading_dir = dirs
    img = _make_image(image_dir, "in-progress", age_days=45)
    _queue_file(reading_dir, "20200101_000000_000000-abc.txt", [img])
    prune_orphaned_images()
    assert img.exists()


def test_malformed_queue_line_does_not_protect_old_image(dirs):
    """A malformed queue line yields no recoverable reference, so an old image is treated as an orphan."""
    image_dir, writing_dir, _ = dirs
    img = _make_image(image_dir, "orphan", age_days=31)
    (writing_dir / "20200101_000000_000000-abc.txt").write_text("not valid json {{{\n")
    prune_orphaned_images()
    assert not img.exists()


def test_unreadable_queue_file_does_not_block_other_orphans(dirs, monkeypatch):
    """A single unreadable queue file is skipped (not fatal), so unrelated old orphans are still pruned.

    Aborting the whole sweep on one bad file would let it silently disable image retention forever.
    """
    image_dir, writing_dir, _ = dirs
    img = _make_image(image_dir, "orphan", age_days=31)
    _queue_file(writing_dir, "20200101_000000_000000-abc.txt", [])

    def _boom(*args, **kwargs):
        raise OSError("cannot read")

    monkeypatch.setattr(Path, "open", _boom)
    prune_orphaned_images()
    assert not img.exists()


def test_file_disappearing_mid_scan_is_benign(dirs, monkeypatch):
    """A queue file renamed/consumed between glob and open (FileNotFoundError) must not break the sweep."""
    image_dir, writing_dir, _ = dirs
    img = _make_image(image_dir, "orphan", age_days=31)
    _queue_file(writing_dir, "20200101_000000_000000-abc.txt", [])

    def _gone(*args, **kwargs):
        raise FileNotFoundError("file moved to reading dir")

    monkeypatch.setattr(Path, "open", _gone)
    prune_orphaned_images()
    assert not img.exists()


def test_ignores_subdirectories(dirs):
    """Non-file entries in the image dir should be skipped without error."""
    image_dir, _, _ = dirs
    (image_dir / "subdir").mkdir()
    _make_image(image_dir, "orphan", age_days=31)
    prune_orphaned_images()  # Should not raise
    assert (image_dir / "subdir").exists()
