"""Tests for mount-s3 drain/probe helpers that do not need FUSE."""

from pathlib import Path

from app.runtime.check_s3_mount import is_mount_point
from app.runtime.mount_s3 import mount_s3_argv, needs_drain, path_statable


def test_is_mount_point_reads_proc_mounts(tmp_path: Path):
    mounts = tmp_path / "mounts"
    mounts.write_text("overlay / overlay rw 0 0\n\nbroken\n")
    assert is_mount_point("/", str(mounts))
    assert not is_mount_point("/not-mounted", str(mounts))


def test_missing_path_is_not_statable(tmp_path):
    missing = str(tmp_path / "no-such-dir" / "x")
    assert not path_statable(missing)
    assert not needs_drain(missing)


def test_zombie_path_needs_drain(tmp_path):
    zombie = tmp_path / "broken-link"
    zombie.symlink_to(tmp_path / "no-such-target")
    assert needs_drain(str(zombie))


def test_mount_s3_argv_falls_back_to_path_binary():
    argv = mount_s3_argv("bucket", "/mnt", "us-west-2", "/cache")
    assert argv[0] == "mount-s3"
    assert "bucket" in argv
    assert "--foreground" in argv
